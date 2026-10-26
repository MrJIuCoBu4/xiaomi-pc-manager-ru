[CmdletBinding()]
param(
 [ValidateSet('Status','Install','Restore','Recover')][string]$Action='Status',
 [string]$TargetPath=(Join-Path $env:ProgramFiles 'MI\XiaomiPCManager\5.8.1.130'),
 [switch]$CameraFix,[switch]$NoOSD,[switch]$RestartOSD
)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$script:Package=Join-Path $PSScriptRoot 'patches'
$script:Root=[IO.Path]::GetFullPath($TargetPath).TrimEnd('\')
$script:Catalog=Get-Content -LiteralPath (Join-Path $script:Package 'catalog.json') -Raw|ConvertFrom-Json
$script:Archives=@{}

function Get-BytesHash([byte[]]$Bytes){
 $sha=[Security.Cryptography.SHA256]::Create()
 try{return [BitConverter]::ToString($sha.ComputeHash($Bytes)).Replace('-','')}finally{$sha.Dispose()}
}
function Get-PathHash([string]$Path){return Get-BytesHash ([IO.File]::ReadAllBytes($Path))}
function Get-SafePath([string]$Base,[string]$Name){
 if([IO.Path]::IsPathRooted($Name) -or $Name.Contains(':') -or ($Name -split '[/\\]') -contains '..'){throw 'Unsafe relative path'}
 $baseFull=[IO.Path]::GetFullPath($Base).TrimEnd('\');$path=[IO.Path]::GetFullPath((Join-Path $baseFull $Name))
 if(-not $path.StartsWith($baseFull+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Path escapes target'}
 $cursor=$path
 while($cursor -and $cursor.Length -ge $baseFull.Length){
  if(Test-Path -LiteralPath $cursor){if(((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw "Reparse path rejected: $cursor"}}
  $cursor=[IO.Path]::GetDirectoryName($cursor)
 }
 return $path
}
function Get-StatePath([string]$Name){return Get-SafePath $script:Root ('.xiaomi-pc-manager-ru/'+$Name)}
function Write-AtomicBytes([string]$Path,[byte[]]$Bytes){
 $dir=[IO.Path]::GetDirectoryName($Path);[IO.Directory]::CreateDirectory($dir)|Out-Null
 $temp=Join-Path $dir ('.ru-'+[guid]::NewGuid().ToString('N')+'.tmp')
 try{
  $stream=[IO.File]::Open($temp,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try{$stream.Write($Bytes,0,$Bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
  if([IO.File]::Exists($Path)){[IO.File]::Replace($temp,$Path,[System.Management.Automation.Language.NullString]::Value)}else{[IO.File]::Move($temp,$Path)}
 }finally{if([IO.File]::Exists($temp)){[IO.File]::Delete($temp)}}
}
function Write-Json([string]$Path,$Value){Write-AtomicBytes $Path ([Text.UTF8Encoding]::new($false).GetBytes(($Value|ConvertTo-Json -Depth 20)))}
function Convert-State($Value){
 $files=@{}
 if($Value){if($Value.schema -ne 1){throw 'Unknown state schema'};if($Value.files -is [Collections.IDictionary]){foreach($key in $Value.files.Keys){$files[$key]=$Value.files[$key]}}else{foreach($p in $Value.files.PSObject.Properties){$files[$p.Name]=$p.Value}}}
 return @{schema=1;files=$files}
}
function Read-State{
 $path=Get-StatePath 'state.json'
 if(Test-Path -LiteralPath $path){return Convert-State (Get-Content -LiteralPath $path -Raw|ConvertFrom-Json)}
 return Convert-State $null
}
function Get-BackupPath([string]$Hash){if($Hash -notmatch '^[A-F0-9]{64}$'){throw 'Invalid backup hash'};return Get-StatePath ('backups/'+$Hash+'.bin')}
function Read-Backup([string]$Hash){
 $bytes=[IO.File]::ReadAllBytes((Get-BackupPath $Hash));if((Get-BytesHash $bytes) -ne $Hash){throw 'Backup checksum mismatch'};return ,$bytes
}
function Save-Backup([string]$Hash,[byte[]]$Bytes){
 $path=Get-BackupPath $Hash
 if(Test-Path -LiteralPath $path){$null=Read-Backup $Hash}else{if((Get-BytesHash $Bytes) -ne $Hash){throw 'Invalid backup source'};Write-AtomicBytes $path $Bytes}
}
function Apply-Delta([byte[]]$Source,[byte[]]$Delta,[long]$Size){
 if($Size -lt 0 -or $Size -gt 128MB -or $Delta.Length -lt 7 -or [Text.Encoding]::ASCII.GetString($Delta,0,6) -ne "XPRD1`0"){throw 'Invalid delta'}
 $inputStream=[IO.MemoryStream]::new($Delta,$false);$reader=[IO.BinaryReader]::new($inputStream);$output=[IO.MemoryStream]::new();$inputStream.Position=6
 try{
  while($inputStream.Position -lt $inputStream.Length){
   $op=$reader.ReadByte()
   if($op -eq 69){if($inputStream.Position -ne $inputStream.Length -or $output.Length -ne $Size){throw 'Invalid delta ending'};return ,$output.ToArray()}
   if($op -eq 67){
    $offset=$reader.ReadUInt64();$length=$reader.ReadUInt64()
    if($offset -gt $Source.LongLength -or $length -gt ($Source.LongLength-$offset) -or $length -gt ($Size-$output.Length)){throw 'Delta copy bounds exceeded'}
    $output.Write($Source,[int]$offset,[int]$length)
   }elseif($op -eq 65){
    $length=$reader.ReadUInt64()
    if($length -gt ($inputStream.Length-$inputStream.Position) -or $length -gt ($Size-$output.Length)){throw 'Delta insert bounds exceeded'}
    $data=$reader.ReadBytes([int]$length);$output.Write($data,0,$data.Length)
   }else{throw 'Unknown delta opcode'}
  }
  throw 'Missing delta ending'
 }finally{$reader.Dispose();$inputStream.Dispose();$output.Dispose()}
}
function Read-Delta($Variant){
 $name=$Variant.archive;if(-not $name){$name=$script:Catalog.archive}
 $expected=$null
 if($name -eq $script:Catalog.archive){$expected=$script:Catalog.archiveSHA256}else{$property=$script:Catalog.supplementalArchives.PSObject.Properties[$name];if($property){$expected=$property.Value}}
 if(-not $expected){throw 'Undeclared patch archive'}
 if(-not $script:Archives.ContainsKey($name)){
  $path=Get-SafePath $script:Package $name
  if((Get-PathHash $path) -ne $expected){throw "Patch archive checksum mismatch: $name"}
  $zip=[IO.Compression.ZipFile]::OpenRead($path);$seen=@{}
  foreach($entry in $zip.Entries){if($seen.ContainsKey($entry.FullName)){$zip.Dispose();throw 'Duplicate ZIP entry'};$seen[$entry.FullName]=$true}
  $script:Archives[$name]=$zip
 }
 $entry=$script:Archives[$name].GetEntry($Variant.entry)
 if(-not $entry -or $entry.Length -gt 128MB){throw 'Missing or oversized delta entry'}
 $stream=$entry.Open();$memory=[IO.MemoryStream]::new()
 try{$stream.CopyTo($memory);$bytes=$memory.ToArray()}finally{$stream.Dispose();$memory.Dispose()}
 if((Get-BytesHash $bytes) -ne $Variant.sha256){throw 'Delta checksum mismatch'}
 return ,$bytes
}
function Assert-Version{
 $camera=$script:Catalog.files|Where-Object component -eq 'camera'
 $hash=Get-PathHash (Get-SafePath $script:Root $camera.path)
 if($hash -ne $camera.original -and $hash -ne $camera.patched){throw 'Unknown Xiaomi version/camera DLL. No files replaced.'}
}
function Invoke-Commit($Plans,$OldState,$NewState){
 foreach($plan in $Plans){Save-Backup $plan.before $plan.BeforeBytes}
 $journal=@{schema=1;plans=@($Plans|ForEach-Object {@{path=$_.path;before=$_.before;after=$_.after}});old=$OldState;new=$NewState}
 Write-Json (Get-StatePath 'pending.json') $journal
 $written=[Collections.Generic.List[object]]::new()
 try{
  foreach($plan in $Plans){
   $path=Get-SafePath $script:Root $plan.path
   if((Get-PathHash $path) -ne $plan.before){throw 'File changed after preflight'}
   $written.Add($plan)
   if((Get-BytesHash $plan.AfterBytes) -ne $plan.after){throw 'Staged checksum mismatch'}
   Write-AtomicBytes $path $plan.AfterBytes
   if((Get-PathHash $path) -ne $plan.after){throw 'Post-write checksum mismatch'}
  }
  Write-Json (Get-StatePath 'state.json') $NewState
  [IO.File]::Delete((Get-StatePath 'pending.json'))
 }catch{
  $reason=$_.Exception.Message;$failures=[Collections.Generic.List[string]]::new()
  for($i=$written.Count-1;$i -ge 0;$i--){
   $plan=$written[$i]
   try{
    $path=Get-SafePath $script:Root $plan.path;$current=Get-PathHash $path
    if($current -ne $plan.before -and $current -ne $plan.after){throw 'Concurrent modification detected'}
    if($current -ne $plan.before){Write-AtomicBytes $path (Read-Backup $plan.before)}
   }catch{$failures.Add($plan.path)}
  }
  if($failures.Count){throw ('Rollback incomplete. Keep backups and run Recover: '+($failures -join ', '))}
  Write-Json (Get-StatePath 'state.json') $OldState;[IO.File]::Delete((Get-StatePath 'pending.json'))
  throw "Operation failed; previous state restored: $reason"
 }
}
function Install-Patch{
 Assert-Version
 $old=Read-State;$new=Convert-State ($old|ConvertTo-Json -Depth 20|ConvertFrom-Json);$plans=[Collections.Generic.List[object]]::new()
 foreach($file in $script:Catalog.files){
  if(($file.component -eq 'camera' -and -not $CameraFix) -or ($file.component -eq 'osd' -and $NoOSD)){continue}
  $path=Get-SafePath $script:Root $file.path;$before=[IO.File]::ReadAllBytes($path);$hash=Get-BytesHash $before
  if($hash -eq $file.patched){continue}
  $variant=$file.variants|Where-Object source -eq $hash|Select-Object -First 1
  if(-not $variant){throw "Unknown file/version: $($file.path)"}
  if($old.files.ContainsKey($file.path) -and $old.files[$file.path].after -ne $hash){throw 'Tracked file changed externally'}
  $after=Apply-Delta $before (Read-Delta $variant) $file.size
  if((Get-BytesHash $after) -ne $file.patched){throw 'Patched checksum mismatch'}
  $plans.Add(@{path=$file.path;before=$hash;after=$file.patched;BeforeBytes=$before;AfterBytes=$after})
  if(-not $new.files.ContainsKey($file.path)){$new.files[$file.path]=@{original=$hash;after=$file.patched}}else{$new.files[$file.path].after=$file.patched}
 }
 if($plans.Count){Invoke-Commit $plans $old $new}
 return $plans.Count
}
function Restore-Patch{
 Assert-Version
 $old=Read-State;$plans=[Collections.Generic.List[object]]::new()
 foreach($name in $old.files.Keys){
  $record=$old.files[$name];$path=Get-SafePath $script:Root $name;$before=[IO.File]::ReadAllBytes($path);$hash=Get-BytesHash $before;$after=Read-Backup $record.original
  if($hash -eq $record.original){continue}
  if($hash -ne $record.after){throw "File changed since installation: $name. Restore blocked."}
  $plans.Add(@{path=$name;before=$hash;after=$record.original;BeforeBytes=$before;AfterBytes=$after})
 }
 if($plans.Count){Invoke-Commit $plans $old (Convert-State $null)}elseif($old.files.Count){Write-Json (Get-StatePath 'state.json') (Convert-State $null)}
 return $plans.Count
}
function Recover-Patch{
 $path=Get-StatePath 'pending.json';if(-not (Test-Path -LiteralPath $path)){return 0}
 $journal=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json;if($journal.schema -ne 1){throw 'Unknown recovery journal'}
 foreach($plan in $journal.plans){$hash=Get-PathHash (Get-SafePath $script:Root $plan.path);if($hash -ne $plan.before -and $hash -ne $plan.after){throw 'Recovery blocked: unknown file'};$null=Read-Backup $plan.before}
 foreach($plan in @($journal.plans)){$target=Get-SafePath $script:Root $plan.path;if((Get-PathHash $target) -ne $plan.before){Write-AtomicBytes $target (Read-Backup $plan.before)}}
 Write-Json (Get-StatePath 'state.json') (Convert-State $journal.old);[IO.File]::Delete($path);return @($journal.plans).Count
}
function Show-Status{
 $counts=@{};$state=Read-State
 foreach($file in $script:Catalog.files){
  $path=Get-SafePath $script:Root $file.path;$hash=$null;if(Test-Path -LiteralPath $path){$hash=Get-PathHash $path}
  $status='UNKNOWN'
  if($hash -eq $file.patched){$status='PATCHED'}elseif($hash -eq $file.original){$status='ORIGINAL'}elseif(@($file.variants|Where-Object source -eq $hash).Count){$status='KNOWN_PREVIOUS'}
  if(-not $counts.ContainsKey($status)){$counts[$status]=0};$counts[$status]++
  if($status -eq 'UNKNOWN'){Write-Host "UNKNOWN: $($file.path)"}
 }
 Write-Host "Xiaomi PC Manager $($script:Catalog.appVersion) / RU $($script:Catalog.release)"
 foreach($key in $counts.Keys){Write-Host "${key}: $($counts[$key])"}
 Write-Host "Tracked backups: $($state.files.Count). Pending recovery: $(Test-Path -LiteralPath (Get-StatePath 'pending.json'))"
}
function Invoke-Patch{
 $lock=$null;$restart=$false
 try{
  if(-not (Test-Path -LiteralPath $script:Root -PathType Container)){throw 'Application directory not found'}
  if($Action -eq 'Status'){Show-Status;return}
  $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
  if(-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Open PowerShell as administrator.'}
  $stateDir=Get-SafePath $script:Root '.xiaomi-pc-manager-ru';[IO.Directory]::CreateDirectory($stateDir)|Out-Null
  $lock=[IO.File]::Open((Get-StatePath 'transaction.lock'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  if($Action -ne 'Recover' -and (Test-Path -LiteralPath (Get-StatePath 'pending.json'))){throw 'Interrupted operation found. Run -Action Recover first.'}
  if(Get-Process -Name XiaomiPcManager -ErrorAction SilentlyContinue){throw 'Exit Xiaomi PC Manager through its tray menu first.'}
  $osd=@(Get-Process -Name OSDUtility -ErrorAction SilentlyContinue)
  if($osd.Count -and -not ($Action -eq 'Install' -and $NoOSD)){
   foreach($p in $osd){if($p.Path -ne (Join-Path $script:Root 'OSDUtility.exe')){throw 'OSD process path is unexpected'}}
   if(-not $RestartOSD){throw 'OSD is running. Use -RestartOSD to restart only this helper.'}
   $restart=$true;$osd|Stop-Process -ErrorAction Stop;foreach($p in $osd){$p.WaitForExit(5000)|Out-Null}
  }
  if($Action -eq 'Install'){$count=Install-Patch}elseif($Action -eq 'Restore'){$count=Restore-Patch}else{$count=Recover-Patch}
  Write-Host "${Action}_OK: $count file(s). Start Xiaomi PC Manager normally."
 }finally{
  foreach($zip in $script:Archives.Values){$zip.Dispose()};$script:Archives=@{}
  if($lock){$lock.Dispose();[IO.File]::Delete((Get-StatePath 'transaction.lock'))}
  if($restart){Start-Process -FilePath (Join-Path $script:Root 'OSDUtility.exe') -WorkingDirectory $script:Root -WindowStyle Hidden|Out-Null}
 }
}
if($MyInvocation.InvocationName -ne '.'){
 try{Invoke-Patch}catch{Write-Host ('FAILED: '+$_.Exception.Message) -ForegroundColor Red;exit 1}
}

