"""Build a small UI-only update against an existing immutable delta catalog."""
import argparse,hashlib,json,pathlib,sys,zipfile
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'src'))
from delta import encode,apply
sha=lambda b:hashlib.sha256(b).hexdigest().upper()
def main():
 p=argparse.ArgumentParser();p.add_argument('--workspace',type=pathlib.Path,required=True);p.add_argument('--base-catalog',type=pathlib.Path,required=True);a=p.parse_args();w=a.workspace
 repo=pathlib.Path(__file__).resolve().parents[1];catalog=json.loads(a.base_catalog.read_text(encoding='utf-8-sig'));archive='cleanup-1.4.4.xpr.zip';retired=[];count=0
 with zipfile.ZipFile(repo/'patches'/archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
  for f in catalog['files']:
   if f['path'] not in ['dist/static/js/main.js','dist/static/css/main.css']:continue
   paths=[w/'outputs/Xiaomi-RU-v1.4.2/backup'/f['path']]
   paths.extend(w/f'outputs/Xiaomi-RU-{version}/payload'/f['path'] for version in ['v1','v1.1','v1.2','v1.3','v1.4','v1.4.1','v1.4.2','v1.4.3'])
   sources={sha(p.read_bytes()):p.read_bytes() for p in paths if p.is_file()};required={f['patched'],*[v['source'] for v in f['variants']]};assert required<=sources.keys()
   target=(w/'outputs/Xiaomi-RU-v1.4.4/payload'/f['path']).read_bytes();retired.extend(v['entry'] for v in f['variants']);variants=[]
   for source_hash in sorted(required):
    source=sources[source_hash];d=encode(source,target);assert apply(source,d,len(target))==target
    key=f"{'js' if f['path'].endswith('.js') else 'css'}-{source_hash[:16]}.xpd";info=zipfile.ZipInfo(key,(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,d)
    variants.append(dict(source=source_hash,archive=archive,entry=key,sha256=sha(d)));count+=1
   f['patched']=sha(target);f['size']=len(target);f['variants']=variants
 catalog['release']='1.4.4-rc.1';catalog['supplementalArchives']={archive:sha((repo/'patches'/archive).read_bytes())};catalog['retiredEntries']={catalog['archive']:retired}
 (repo/'patches/catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print('PASS:',count,'update deltas;', (repo/'patches'/archive).stat().st_size,'bytes')
if __name__=='__main__':main()
