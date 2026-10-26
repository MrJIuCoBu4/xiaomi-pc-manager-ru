[CmdletBinding()]
param(
 [ValidateSet('Status','Install','Restore','Recover')][string]$Action='Status',
 [string]$TargetPath=(Join-Path $env:ProgramFiles 'MI\XiaomiPCManager\5.8.1.130'),
 [switch]$CameraFix,
 [switch]$NoOSD,
 [switch]$RestartOSD
)
$ErrorActionPreference='Stop'
# No automatic downloads, elevation or execution-policy changes.
$launcher=Get-Command py -ErrorAction SilentlyContinue
$prefix=@('-3')
if(-not $launcher){$launcher=Get-Command python -ErrorAction SilentlyContinue;$prefix=@()}
if(-not $launcher){throw 'Python 3.10+ is required. Install Python, then run this script again.'}
$version=& $launcher.Source @prefix -c 'import sys; print(int(sys.version_info >= (3,10)))'
if($LASTEXITCODE -ne 0 -or $version -ne '1'){throw 'A working Python 3.10+ installation is required.'}
$arguments=@((Join-Path $PSScriptRoot 'patch.py'),$Action.ToLowerInvariant(),'--target',$TargetPath)
if($CameraFix){$arguments+='--camera-fix'}
if($NoOSD){$arguments+='--no-osd'}
if($RestartOSD){$arguments+='--restart-osd'}
& $launcher.Source @prefix @arguments
exit $LASTEXITCODE
