"""Maintainer-only: build deltas from private, locally held Xiaomi files."""
import argparse, hashlib, json, pathlib, sys, zipfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
from delta import encode, apply

def sha(data): return hashlib.sha256(data).hexdigest().upper()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=pathlib.Path,required=True);a=parser.parse_args()
    repo=pathlib.Path(__file__).resolve().parents[1];w=a.workspace;old=w/'outputs/Xiaomi-RU-v1.4.2';last=w/'outputs/Xiaomi-RU-v1.4.3'
    private=json.loads((old/'manifest.json').read_text(encoding='utf-8-sig'))
    rows=[]
    for f in private['files']:
        path=f['name'].replace('\\','/');target=(last/'payload'/path if f['name'].endswith('main.css') else old/'payload'/path).read_bytes()
        original=(old/'backup'/path).read_bytes()
        assert sha(original)==f['original'],path
        sources={sha(original):original}
        # Accept earlier development UI builds without discarding user state on rollback.
        if f['group']!='OSD':
            for version in ['v1','v1.1','v1.2','v1.3','v1.4','v1.4.1','v1.4.2']:
                p=w/f'outputs/Xiaomi-RU-{version}/payload'/path
                if p.is_file(): sources.setdefault(sha(p.read_bytes()),p.read_bytes())
        rows.append((path,f['group'],original,target,sources))
    original=(w/'outputs/camera-patch-backup/PcControlCenter.dll').read_bytes();target=(w/'outputs/PcControlCenter.patched.dll').read_bytes()
    assert sha(original)=='07CF478B75AD5045A61E27DA47DBDEFB11E45AEC2B67BD6D33458772B84ADBCD'
    assert sha(target)=='E7004E2B57B37014EB60C274CDA07F70F6CB1664E1D6EF396F46E2C5A56472C9'
    rows.append(('PcControlCenter.dll','CAMERA',original,target,{sha(original):original}))
    archive=repo/'patches/5.8.1.130.xpr.zip';files=[];verified=0
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for i,(path,group,original,target,sources) in enumerate(rows):
            variants=[]
            for source_hash,source in sources.items():
                if source_hash==sha(target):continue
                delta=encode(source,target);assert apply(source,delta,len(target))==target
                key=f'{i:04d}-{source_hash[:16]}.xpd';info=zipfile.ZipInfo(key,(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                z.writestr(info,delta);variants.append(dict(source=source_hash,entry=key,sha256=sha(delta)));verified+=1
            files.append(dict(path=path,component='camera' if group=='CAMERA' else 'osd' if group=='OSD' else 'ui',original=sha(original),patched=sha(target),size=len(target),variants=variants))
            if i%100==0:print('Verified',i,'files',flush=True)
    catalog=dict(schema=1,release='1.4.3-rc.1',appVersion='5.8.1.130',archive=archive.name,archiveSHA256=sha(archive.read_bytes()),files=files)
    (repo/'patches/catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    (w/'outputs/community-build-validation.json').write_text(json.dumps(dict(files=len(files),deltaRoundtrips=verified,archiveSize=archive.stat().st_size,archiveSHA256=catalog['archiveSHA256']),indent=2),encoding='utf8')
    print('PASS:',len(files),'files,',verified,'delta roundtrips;',archive.stat().st_size,'bytes')
if __name__=='__main__':main()
