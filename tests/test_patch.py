import hashlib,json,pathlib,sys,tempfile,unittest,zipfile,struct
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'src'))
from delta import encode,apply,MAGIC
from engine import Engine,PatchError,digest,safe_path,json_write,atomic_write

class DeltaTests(unittest.TestCase):
 def test_roundtrip(self):
  for a,b in [(b'',b''),(b'abc',b'abcdef'),(b'abcd'*1000,b'head'+b'abcd'*900+b'tail'),(bytes(range(256))*20,b'xyz')]:
   self.assertEqual(apply(a,encode(a,b),len(b)),b)
 def test_bounds_and_truncation(self):
  for d in [b'bad',MAGIC+b'C'+struct.pack('<QQ',999,5)+b'E',MAGIC+b'A'+struct.pack('<Q',100)+b'x',MAGIC+b'Ejunk']:
   with self.assertRaises(ValueError):apply(b'abc',d,3)

class EngineTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=pathlib.Path(self.tmp.name);self.root=self.base/'app';self.root.mkdir();self.pkg=self.base/'patches';self.pkg.mkdir()
  self.original={'a.bin':b'first-original','nested/b.bin':b'second-original','PcControlCenter.dll':b'camera-original'}
  self.patched={k:v+b'-translated' for k,v in self.original.items()};files=[]
  with zipfile.ZipFile(self.pkg/'test.zip','w') as z:
   for i,(k,v) in enumerate(self.original.items()):
    p=self.root/k;p.parent.mkdir(exist_ok=True);p.write_bytes(v);d=encode(v,self.patched[k]);z.writestr(str(i),d)
    files.append(dict(path=k,component='camera' if k.endswith('.dll') else 'ui',original=digest(v),patched=digest(self.patched[k]),size=len(self.patched[k]),variants=[dict(source=digest(v),entry=str(i),sha256=digest(d))]))
  json_write(self.pkg/'catalog.json',dict(schema=1,appVersion='5.8.1.130',release='test',archive='test.zip',archiveSHA256=digest((self.pkg/'test.zip').read_bytes()),files=files))
  self.e=Engine(self.root,self.pkg)
 def tearDown(self):self.tmp.cleanup()
 def check_original(self):
  for name,data in self.original.items():self.assertEqual((self.root/name).read_bytes(),data)
 def test_install_idempotency_restore_camera_opt_in(self):
  self.assertEqual(self.e.install(),2);self.assertEqual(self.e.install(),0)
  self.assertEqual((self.root/'PcControlCenter.dll').read_bytes(),self.original['PcControlCenter.dll'])
  self.assertEqual(self.e.install(camera=True),1);self.assertEqual(self.e.restore(),3);self.check_original()
 def test_existing_camera_patch_is_preserved(self):
  (self.root/'PcControlCenter.dll').write_bytes(self.patched['PcControlCenter.dll'])
  self.e.install(camera=True);self.e.restore()
  self.assertEqual((self.root/'PcControlCenter.dll').read_bytes(),self.patched['PcControlCenter.dll'])
 def test_unknown_file_rejected_before_write(self):
  (self.root/'nested/b.bin').write_bytes(b'unknown')
  with self.assertRaises(PatchError):self.e.install()
  self.assertEqual((self.root/'a.bin').read_bytes(),self.original['a.bin'])
 def test_corrupt_archive_rejected(self):
  with (self.pkg/'test.zip').open('ab') as f:f.write(b'tampered')
  with self.assertRaises(PatchError):self.e.install()
  self.check_original()
 def test_write_failure_rolls_back(self):
  with self.assertRaisesRegex(PatchError,'previous state restored'):self.e.install(camera=True,fail_after=1)
  self.check_original();self.assertFalse(self.e.pending_path.exists())
 def test_unknown_post_install_blocks_restore(self):
  self.e.install();(self.root/'nested/b.bin').write_bytes(b'updated-by-vendor')
  with self.assertRaises(PatchError):self.e.restore()
  self.assertEqual((self.root/'a.bin').read_bytes(),self.patched['a.bin'])
 def test_corrupt_backup_blocks_restore(self):
  self.e.install();self.e.backup_path(digest(self.original['a.bin'])).write_bytes(b'bad')
  with self.assertRaises(PatchError):self.e.restore()
 def test_interrupted_operation_recovery(self):
  before=digest(self.original['a.bin']);after=digest(self.patched['a.bin']);atomic_write(self.e.backup_path(before),self.original['a.bin'])
  json_write(self.e.pending_path,dict(schema=1,plans=[dict(path='a.bin',before=before,after=after)],old=dict(schema=1,files={})))
  (self.root/'a.bin').write_bytes(self.patched['a.bin'])
  with self.assertRaises(PatchError):self.e.install()
  self.assertEqual(self.e.recover(),1);self.check_original()
 def test_recovery_refuses_external_changes(self):
  before=digest(self.original['a.bin']);atomic_write(self.e.backup_path(before),self.original['a.bin'])
  json_write(self.e.pending_path,dict(schema=1,plans=[dict(path='a.bin',before=before,after=digest(b'after'))],old=dict(schema=1,files={})))
  (self.root/'a.bin').write_bytes(b'unknown')
  with self.assertRaises(PatchError):self.e.recover()
 def test_path_traversal_and_symlink(self):
  for name in ['../outside','/absolute','C:/outside','a/../../outside']:
   with self.assertRaises(PatchError):safe_path(self.root,name)
  try:(self.root/'link').symlink_to(self.base,target_is_directory=True)
  except OSError:return
  with self.assertRaises(PatchError):safe_path(self.root,'link/outside')
 def test_concurrent_operation_lock(self):
  self.e.lock()
  try:
   with self.assertRaises(PatchError):self.e.install()
  finally:self.e.unlock()

if __name__=='__main__':unittest.main()
