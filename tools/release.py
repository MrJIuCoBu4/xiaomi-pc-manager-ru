"""Build a deterministic source+delta release ZIP. Never publish directly."""
import argparse,hashlib,pathlib,zipfile,json

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
 root=pathlib.Path(__file__).resolve().parents[1];c=json.loads((root/'patches/catalog.json').read_text(encoding='utf8'));a.output.mkdir(parents=True,exist_ok=True)
 name=f"xiaomi-pc-manager-ru-{c['release']}-for-{c['appVersion']}.zip";dest=a.output/name
 tops={'src','tools','tests','docs','patches','translations','.github'};files=[]
 for item in root.iterdir():
  if item.is_file() and item.name in ['README.md','Patch.ps1','patch.py','LICENSE','CHANGELOG.md','CONTRIBUTING.md','.gitignore']:files.append(item)
  elif item.is_dir() and item.name in tops:files.extend(x for x in item.rglob('*') if x.is_file() and '__pycache__' not in x.parts and x.suffix!='.pyc')
 with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
  for f in sorted(files,key=lambda item:item.relative_to(root).as_posix()):
   info=zipfile.ZipInfo(str(f.relative_to(root)).replace('\\','/'),(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.create_system=3;info.external_attr=0o100644<<16;z.writestr(info,f.read_bytes())
 sha=hashlib.sha256(dest.read_bytes()).hexdigest().upper();(a.output/'SHA256SUMS.txt').write_text(f'{sha}  {name}\n',encoding='ascii')
 print(name,dest.stat().st_size,'bytes',sha)
if __name__=='__main__':main()

