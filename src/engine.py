"""Hash-guarded file patching with an on-disk recovery journal (Python stdlib only)."""
import hashlib, json, os, pathlib, shutil, tempfile, uuid, zipfile
from delta import apply, MAX_FILE_SIZE

class PatchError(RuntimeError): pass

def digest(data): return hashlib.sha256(data).hexdigest().upper()
def hash_file(path): return digest(path.read_bytes())
def safe_path(root, name):
    p=pathlib.PurePosixPath(name.replace('\\','/'))
    if p.is_absolute() or not p.parts or any(x in ('..','.') or ':' in x for x in p.parts):
        raise PatchError('Unsafe relative path: '+name)
    root=root.resolve(); candidate=root.joinpath(*p.parts)
    # Reject symlinks/junctions at every existing level, even if they point inside the root.
    cursor=root
    for part in p.parts:
        cursor=cursor/part
        if cursor.is_symlink() or (hasattr(cursor,'is_junction') and cursor.is_junction()):
            raise PatchError('Reparse path rejected: '+name)
        try:
            if cursor.lstat().st_file_attributes & 0x400: raise PatchError('Reparse path rejected: '+name)
        except (AttributeError,FileNotFoundError): pass
    try: candidate.resolve().relative_to(root)
    except ValueError: raise PatchError('Path escapes target')
    return candidate

def atomic_write(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.xpr-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp): os.unlink(temp)

def json_write(path,value): atomic_write(path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
def json_read(path,default): return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else default

class Engine:
    def __init__(self, root, package):
        self.root=pathlib.Path(root).resolve();self.package=pathlib.Path(package).resolve()
        self.catalog=json_read(self.package/'catalog.json',None)
        if not self.catalog or self.catalog.get('schema')!=1:raise PatchError('Unsupported catalog')
        if not self.root.is_dir():raise PatchError('Application directory not found: '+str(self.root))
        names=[f['path'] for f in self.catalog['files']]
        if len(names)!=len(set(x.casefold() for x in names)):raise PatchError('Duplicate catalog paths')
        for name in names:safe_path(self.root,name)
        self.state_dir=safe_path(self.root,'.xiaomi-pc-manager-ru')
        self.state_path=safe_path(self.root,'.xiaomi-pc-manager-ru/state.json')
        self.pending_path=safe_path(self.root,'.xiaomi-pc-manager-ru/pending.json')
        self.lock_path=safe_path(self.root,'.xiaomi-pc-manager-ru/transaction.lock')
    def state(self):
        state=json_read(self.state_path,{'schema':1,'files':{}})
        if state.get('schema')!=1 or not isinstance(state.get('files'),dict):raise PatchError('Invalid local state')
        return state
    def lock(self):
        self.state_dir.mkdir(exist_ok=True)
        try:fd=os.open(self.lock_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError:raise PatchError('Another operation may be running. See docs/RECOVERY.md (transaction.lock).')
        os.close(fd)
    def unlock(self):self.lock_path.unlink(missing_ok=True)
    def backup_path(self, sha):
        if len(sha)!=64 or any(c not in '0123456789ABCDEF' for c in sha):raise PatchError('Invalid backup hash')
        return safe_path(self.root,'.xiaomi-pc-manager-ru/backups/'+sha+'.bin')
    def verified_backup(self,sha):
        data=self.backup_path(sha).read_bytes()
        if digest(data)!=sha:raise PatchError('Backup hash mismatch: '+sha)
        return data
    def status(self):
        state=self.state();rows=[]
        for f in self.catalog['files']:
            p=safe_path(self.root,f['path']);h=hash_file(p) if p.is_file() else None
            if h==f['patched']:label='PATCHED'
            elif h==f['original']:label='ORIGINAL'
            elif h in [v['source'] for v in f['variants']]:label='KNOWN_PREVIOUS'
            else:label='UNKNOWN'
            if f['path'] in state['files'] and h==state['files'][f['path']]['after']:label='PATCHED_TRACKED'
            rows.append(dict(path=f['path'],component=f['component'],status=label))
        return dict(version=self.catalog['appVersion'],release=self.catalog['release'],pending=self.pending_path.exists(),locked=self.lock_path.exists(),tracked=len(state['files']),files=rows)
    def check_version(self):
        camera=next(f for f in self.catalog['files'] if f['component']=='camera')
        if hash_file(safe_path(self.root,camera['path'])) not in (camera['original'],camera['patched']):
            raise PatchError('Application camera DLL/version is unknown; no files changed.')
    def install(self, camera=False, osd=True, fail_after=None):
        self.lock()
        try:
            if self.pending_path.exists():raise PatchError('Interrupted operation found. Run recover first.')
            self.check_version();old=self.state();new=json.loads(json.dumps(old));plans=[]
            archive=safe_path(self.package,self.catalog['archive'])
            if hash_file(archive)!=self.catalog['archiveSHA256']:raise PatchError('Patch archive checksum mismatch')
            # Validate every selected source before staging or replacing any application file.
            for f in self.catalog['files']:
                if (f['component']=='camera' and not camera) or (f['component']=='osd' and not osd):continue
                path=safe_path(self.root,f['path']);before=hash_file(path)
                if before==f['patched']:continue
                variant=next((v for v in f['variants'] if v['source']==before),None)
                if variant is None:raise PatchError('Unknown file/version: '+f['path'])
                tracked=old['files'].get(f['path'])
                if tracked and before!=tracked['after']:raise PatchError('Tracked file changed externally: '+f['path'])
                plans.append(dict(path=f['path'],before=before,after=f['patched'],size=f['size'],variant=variant))
            if not plans:return 0
            if shutil.disk_usage(self.root).free < sum(x['size'] for x in plans)*3+10*1024*1024:
                raise PatchError('Insufficient free space for staging and backups')
            stage=safe_path(self.root,'.xiaomi-pc-manager-ru/stage-'+uuid.uuid4().hex);stage.mkdir()
            try:
                with zipfile.ZipFile(archive) as z:
                    if len(z.namelist())!=len(set(z.namelist())):raise PatchError('Duplicate archive entries')
                    for i,plan in enumerate(plans):
                        variant=plan['variant'];info=z.getinfo(variant['entry'])
                        if info.file_size>MAX_FILE_SIZE:raise PatchError('Delta exceeds size limit')
                        delta=z.read(info)
                        if digest(delta)!=variant['sha256']:raise PatchError('Delta checksum mismatch')
                        source=safe_path(self.root,plan['path']).read_bytes()
                        if digest(source)!=plan['before']:raise PatchError('Source changed during staging')
                        result=apply(source,delta,plan['size'])
                        if digest(result)!=plan['after']:raise PatchError('Patched checksum mismatch')
                        stage_file=stage/str(i);stage_file.write_bytes(result);plan['stage']=str(stage_file.relative_to(self.root)).replace('\\','/')
                        backup=self.backup_path(plan['before'])
                        if backup.exists():self.verified_backup(plan['before'])
                        else:atomic_write(backup,source)
                        new['files'].setdefault(plan['path'],{'original':plan['before'],'after':plan['after']})
                        new['files'][plan['path']]['after']=plan['after']
                self.commit(plans,old,new,fail_after)
                return len(plans)
            finally:shutil.rmtree(stage)
        finally:self.unlock()
    def commit(self, plans, old, new, fail_after=None):
        journal={'schema':1,'plans':[{k:p[k] for k in ('path','before','after')} for p in plans],'old':old,'new':new}
        json_write(self.pending_path,journal);written=[]
        try:
            for i,p in enumerate(plans):
                path=safe_path(self.root,p['path'])
                if hash_file(path)!=p['before']:raise PatchError('Target changed after preflight: '+p['path'])
                written.append(p)
                if fail_after is not None and i==fail_after:raise OSError('Injected write failure')
                result=safe_path(self.root,p['stage']).read_bytes() if 'stage' in p else self.verified_backup(p['after'])
                if digest(result)!=p['after']:raise PatchError('Staged file hash mismatch')
                atomic_write(path,result)
                if hash_file(path)!=p['after']:raise PatchError('Post-write hash mismatch')
            json_write(self.state_path,new);self.pending_path.unlink()
        except BaseException as failure:
            errors=[]
            for p in reversed(written):
                try:
                    path=safe_path(self.root,p['path']);current=hash_file(path)
                    if current not in (p['before'],p['after']):raise PatchError('Concurrent modification; will not overwrite')
                    if current!=p['before']:atomic_write(path,self.verified_backup(p['before']))
                except Exception as error:errors.append(str(error))
            if errors:raise PatchError('Rollback incomplete. Preserve backups and run recover: '+'; '.join(errors)) from failure
            json_write(self.state_path,old);self.pending_path.unlink(missing_ok=True)
            raise PatchError('Operation failed; previous state restored: '+str(failure)) from failure
    def restore(self,fail_after=None):
        self.lock()
        try:
            if self.pending_path.exists():raise PatchError('Run recover before restore')
            old=self.state();plans=[]
            for name,record in old['files'].items():
                path=safe_path(self.root,name);current=hash_file(path);self.verified_backup(record['original'])
                if current==record['original']:continue
                if current!=record['after']:raise PatchError('File changed after patch/update; restore blocked: '+name)
                # Keep the current bytes as well, so an interrupted restore can itself be rolled back.
                backup=self.backup_path(current)
                if backup.exists():self.verified_backup(current)
                else:atomic_write(backup,path.read_bytes())
                plans.append(dict(path=name,before=current,after=record['original']))
            if plans:self.commit(plans,old,{'schema':1,'files':{}},fail_after)
            elif old['files']:json_write(self.state_path,{'schema':1,'files':{}})
            return len(plans)
        finally:self.unlock()
    def recover(self):
        self.lock()
        try:
            j=json_read(self.pending_path,None)
            if j is None:return 0
            if j.get('schema')!=1:raise PatchError('Unknown recovery journal')
            for p in j['plans']:
                current=hash_file(safe_path(self.root,p['path']))
                if current not in (p['before'],p['after']):raise PatchError('Recovery blocked by unknown file: '+p['path'])
                self.verified_backup(p['before'])
            for p in reversed(j['plans']):
                path=safe_path(self.root,p['path'])
                if hash_file(path)!=p['before']:atomic_write(path,self.verified_backup(p['before']))
            json_write(self.state_path,j['old']);self.pending_path.unlink();return len(j['plans'])
        finally:self.unlock()
