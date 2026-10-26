"""Verify public catalog, payload checksums and release hygiene without Xiaomi binaries."""
import hashlib,json,pathlib,sys,zipfile
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'src'))
from delta import MAGIC,MAX_FILE_SIZE

def main():
 root=pathlib.Path(__file__).resolve().parents[1];c=json.loads((root/'patches/catalog.json').read_text(encoding='utf8'));archive=root/'patches'/c['archive']
 assert c['schema']==1 and c['appVersion']=='5.8.1.130'
 assert hashlib.sha256(archive.read_bytes()).hexdigest().upper()==c['archiveSHA256'],'Archive hash mismatch'
 names=set();entries=set();count=0
 with zipfile.ZipFile(archive) as z:
  assert len(z.namelist())==len(set(z.namelist())),'Duplicate ZIP entries'
  for f in c['files']:
   path=pathlib.PurePosixPath(f['path']);assert not path.is_absolute() and '..' not in path.parts and ':' not in f['path']
   assert f['path'].casefold() not in names;names.add(f['path'].casefold())
   assert 0<=f['size']<=MAX_FILE_SIZE
   assert f['component'] in ['ui','osd','camera']
   for h in [f['original'],f['patched']]+[v['source'] for v in f['variants']]:assert len(h)==64 and all(x in '0123456789ABCDEF' for x in h)
   for v in f['variants']:
    assert v['entry'] not in entries;entries.add(v['entry']);assert z.getinfo(v['entry']).file_size<=MAX_FILE_SIZE
    d=z.read(v['entry']);assert d.startswith(MAGIC);assert hashlib.sha256(d).hexdigest().upper()==v['sha256'];count+=1
  assert entries==set(z.namelist()),'Unexpected payload entries'
 forbidden=[]
 for p in root.rglob('*'):
  rel=p.relative_to(root)
  if '.git' in rel.parts or '__pycache__' in rel.parts:continue
  if p.is_file() and p.suffix.lower() in ['.dll','.exe','.pri','.bin','.log']:forbidden.append(str(rel))
 assert not forbidden,forbidden
 print('PASS:',len(c['files']),'files,',count,'delta checksums; no standalone proprietary binaries in repository.')
if __name__=='__main__':main()
