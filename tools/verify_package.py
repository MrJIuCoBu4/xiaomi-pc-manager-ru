"""Verify public catalog, payload checksums and release hygiene without Xiaomi binaries."""
import hashlib,json,pathlib,sys,zipfile
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'src'))
from delta import MAGIC,MAX_FILE_SIZE

def main():
 root=pathlib.Path(__file__).resolve().parents[1];c=json.loads((root/'patches/catalog.json').read_text(encoding='utf8'))
 assert c['schema']==1 and c['appVersion']=='5.8.1.130'
 archives={c['archive']:c['archiveSHA256'],**c.get('supplementalArchives',{})};members={};references={name:set() for name in archives};count=0
 for name,expected in archives.items():
  assert pathlib.PurePosixPath(name).name==name
  archive=root/'patches'/name;assert hashlib.sha256(archive.read_bytes()).hexdigest().upper()==expected,'Archive hash mismatch'
  with zipfile.ZipFile(archive) as z:
   assert len(z.namelist())==len(set(z.namelist())),'Duplicate ZIP entries'
   members[name]={}
   for info in z.infolist():
    assert info.file_size<=MAX_FILE_SIZE;d=z.read(info);assert d.startswith(MAGIC)
    members[name][info.filename]=hashlib.sha256(d).hexdigest().upper()
 names=set()
 for f in c['files']:
  path=pathlib.PurePosixPath(f['path']);assert not path.is_absolute() and '..' not in path.parts and ':' not in f['path']
  assert f['path'].casefold() not in names;names.add(f['path'].casefold());assert 0<=f['size']<=MAX_FILE_SIZE
  assert f['component'] in ['ui','osd','camera']
  for h in [f['original'],f['patched']]+[v['source'] for v in f['variants']]:assert len(h)==64 and all(x in '0123456789ABCDEF' for x in h)
  for v in f['variants']:
   archive=v.get('archive',c['archive']);assert archive in archives
   assert v['entry'] not in references[archive];references[archive].add(v['entry'])
   assert members[archive][v['entry']]==v['sha256'];count+=1
 for name in archives:
  retired=set(c.get('retiredEntries',{}).get(name,[]));assert not retired&references[name]
  assert references[name]|retired==set(members[name]),'Unexpected archive entries'
 forbidden=[]
 for p in root.rglob('*'):
  rel=p.relative_to(root)
  if '.git' in rel.parts or '__pycache__' in rel.parts:continue
  if p.is_file() and p.suffix.lower() in ['.dll','.exe','.pri','.bin','.log']:forbidden.append(str(rel))
 assert not forbidden,forbidden
 print('PASS:',len(c['files']),'files,',count,'active delta checksums; no standalone proprietary binaries in repository.')
if __name__=='__main__':main()
