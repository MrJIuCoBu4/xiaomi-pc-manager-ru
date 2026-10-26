#!/usr/bin/env python3
"""Windows entry point. No network downloads, registry edits or service changes."""
import argparse, collections, ctypes, json, os, pathlib, subprocess, sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent/'src'))
from engine import Engine, PatchError

def processes():
    shell=pathlib.Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    code="@(Get-Process -Name XiaomiPcManager,OSDUtility -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,Path) | ConvertTo-Json -Compress"
    run=subprocess.run([str(shell),'-NoLogo','-NoProfile','-NonInteractive','-Command',code],capture_output=True,text=True,check=True)
    data=json.loads(run.stdout.strip() or '[]')
    return data if isinstance(data,list) else [data]

def stop_verified_osd(pid, expected):
    from ctypes import wintypes
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
    k.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    k.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT];k.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];k.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=k.OpenProcess(0x1000|0x1|0x100000,False,pid)
    if not handle:raise PatchError('Cannot open OSD helper; no processes stopped')
    try:
        buffer=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(buffer))
        if not k.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):raise PatchError('Cannot verify OSD path')
        if os.path.normcase(os.path.realpath(buffer.value))!=os.path.normcase(str(expected.resolve())):raise PatchError('OSD process path differs; refusing to stop it')
        if not k.TerminateProcess(handle,0):raise PatchError('Cannot stop OSD helper')
        if k.WaitForSingleObject(handle,5000)!=0:raise PatchError('OSD did not exit')
    finally:k.CloseHandle(handle)

def main():
    p=argparse.ArgumentParser(description='Xiaomi PC Manager RU 1.4.5-rc.1')
    p.add_argument('action',choices=['status','install','restore','recover'])
    p.add_argument('--target',type=pathlib.Path,default=pathlib.Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'MI/XiaomiPCManager/5.8.1.130')
    p.add_argument('--camera-fix',action='store_true',help='Explicitly opt into modifying PcControlCenter.dll')
    p.add_argument('--no-osd',action='store_true',help='Install only UI, leaving OSD files as they are')
    p.add_argument('--restart-osd',action='store_true',help='Allow restart of the OSD helper at the verified application path')
    p.add_argument('--json',action='store_true',help='Machine readable status')
    a=p.parse_args();restarted=False;root=a.target.resolve()
    try:
        engine=Engine(root,pathlib.Path(__file__).resolve().parent/'patches')
        if a.action=='status':
            status=engine.status()
            if a.json:print(json.dumps(status,ensure_ascii=False,indent=2))
            else:
                print('Xiaomi PC Manager',status['version'],'/ RU',status['release'])
                print(dict(collections.Counter(x['status'] for x in status['files'])))
                print('Tracked backups:',status['tracked'],'Pending recovery:',status['pending'],'Installer lock:',status['locked'])
                for f in status['files']:
                    if f['status']=='UNKNOWN':print('UNKNOWN:',f['path'])
            return 0
        if os.name!='nt':raise PatchError('Installation is supported only on Windows')
        if not ctypes.windll.shell32.IsUserAnAdmin():raise PatchError('Open PowerShell as administrator; no files changed.')
        running=processes()
        if any(x['ProcessName'].casefold()=='xiaomipcmanager' for x in running):raise PatchError('Exit Xiaomi PC Manager through its tray menu first.')
        osd=[x for x in running if x['ProcessName'].casefold()=='osdutility']
        if osd and (a.action!='install' or not a.no_osd):
            if not a.restart_osd:raise PatchError('OSDUtility is running. Use --restart-osd or close the helper first.')
            # Validate all paths before stopping even the first helper.
            expected=root/'OSDUtility.exe'
            if any(not x.get('Path') or os.path.normcase(os.path.realpath(x['Path']))!=os.path.normcase(str(expected)) for x in osd):raise PatchError('OSDUtility from another directory is running; refusing to stop it.')
            for x in osd:stop_verified_osd(int(x['Id']),expected);restarted=True
        if a.action=='install':count=engine.install(camera=a.camera_fix,osd=not a.no_osd)
        elif a.action=='restore':count=engine.restore()
        else:count=engine.recover()
        print(a.action.upper()+'_OK:',count,'file(s). Start Xiaomi PC Manager normally. No Windows restart required.')
        return 0
    except (PatchError,OSError,ValueError,KeyError,subprocess.SubprocessError) as e:
        print('FAILED:',e,file=sys.stderr);return 1
    finally:
        if restarted:
            try:subprocess.Popen([str(root/'OSDUtility.exe')],cwd=root,creationflags=subprocess.CREATE_NO_WINDOW)
            except OSError as e:print('OSD restart failed:',e,'Start OSDUtility.exe normally.',file=sys.stderr)

if __name__=='__main__':sys.exit(main())
