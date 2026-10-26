from PIL import Image,ImageDraw,ImageFont,ImageChops
import pathlib,shutil,json,hashlib,re
import argparse
parser=argparse.ArgumentParser(description='Maintainer PNG authoring helper; requires Pillow')
parser.add_argument('--input',type=pathlib.Path,required=True)
parser.add_argument('--output',type=pathlib.Path,required=True)
args=parser.parse_args()
src=args.input;out=args.output;out.mkdir(parents=True,exist_ok=False)
labels={'KeyboardLightAuto':'Авто','MuteOff':'Микрофон вкл.','MuteOn':'Микрофон выкл.','NewIntelligentMode':'Умный режим','NewLongBatteryMode':'Экономия заряда','WorkloadBalance':'Баланс','WorkloadDeception':'Турборежим','WorkloadSilent':'Тихий режим','WorkloadSpeed':'Быстрый режим','WorkloadTurbo':'Макс. скорость'}
fontpath='C:/Windows/Fonts/seguisb.ttf';report=[]
for p in sorted(src.glob('*.png')):
 stem=p.stem.split('_Dark')[0].split('_Light')[0];stem=stem.removesuffix('_En');label=labels.get(stem)
 if re.fullmatch('DisFre[0-9]+',stem):label='Гц'
 dest=out/p.name
 if not label:shutil.copyfile(p,dest);continue
 original=Image.open(p).convert('RGBA');im=original.copy();w,h=im.size;scale=w/160;hz=label=='Гц'
 box=(round(8*scale),round((104 if hz else 118)*scale),round(152*scale),round(145*scale))
 bg=im.getpixel((round(8*scale),round(115*scale)));color=(255,255,255,255) if '_Dark' in p.stem else (36,36,36,255)
 layer=Image.new('RGBA',((box[2]-box[0])*4,(box[3]-box[1])*4),bg);d=ImageDraw.Draw(layer);size=round((18 if hz else 14)*scale*4)
 while True:
  font=ImageFont.truetype(fontpath,size);bb=d.textbbox((0,0),label,font=font)
  if bb[2]-bb[0]<=layer.width-round(4*scale*4):break
  size-=1
 x=(layer.width-(bb[2]-bb[0]))/2-bb[0];y=(layer.height-(bb[3]-bb[1]))/2-bb[1]
 # Draw glyphs on transparent layer then composite to retain semitransparent background.
 glyph=Image.new('RGBA',layer.size);ImageDraw.Draw(glyph).text((x,y),label,font=font,fill=color)
 layer=Image.alpha_composite(layer,glyph).resize((box[2]-box[0],box[3]-box[1]),Image.Resampling.LANCZOS)
 im.paste(layer,(box[0],box[1]));im.save(dest,optimize=True)
 diff=ImageChops.difference(original,im);outside=diff.copy();ImageDraw.Draw(outside).rectangle((box[0],box[1],box[2]-1,box[3]-1),fill=(0,0,0,0))
 assert not any(channel.getbbox() for channel in outside.split()),p.name
 assert im.size==original.size
 report.append(dict(name=p.name,russian=label,box=box,fontPixels=round(size/4,2),outsideTextUnchanged=True,original=hashlib.sha256(p.read_bytes()).hexdigest().upper(),patched=hashlib.sha256(dest.read_bytes()).hexdigest().upper()))
(out/'translation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
(out/'image-names.txt').write_text('\n'.join(p.name for p in sorted(out.glob('*.png')))+'\n',encoding='utf8')
print('Changed',len(report),'of',len(list(src.glob('*.png'))),'images; unchanged icon pixels verified')
# Preview on a neutral background, both themes.
preview=Image.new('RGB',(1000,420),(80,80,80));draw=ImageDraw.Draw(preview)
for i,name in enumerate(['KeyboardLightAuto','WorkloadSilent','WorkloadBalance','WorkloadSpeed','WorkloadTurbo']):
 for row,theme in enumerate(['Dark','Light']):
  im=Image.open(out/f'{name}_{theme}.png');preview.paste(im,(i*200+20,row*210+10),im)
preview.save(out/'preview.png')
