param([string]$PatchPath=(Join-Path $PSScriptRoot '../Patch.ps1'))
$ErrorActionPreference='Stop'
$base=[IO.Path]::GetFullPath((Join-Path $env:TEMP ('xiaomi-ru-test-'+[guid]::NewGuid().ToString('N'))))
[IO.Directory]::CreateDirectory($base)|Out-Null
. $PatchPath -TargetPath $base -Action Status
$script:Package=Join-Path $base 'package';[IO.Directory]::CreateDirectory($script:Package)|Out-Null
$script:Root=Join-Path $base 'app';[IO.Directory]::CreateDirectory($script:Root)|Out-Null
$CameraFix=$false;$NoOSD=$false
function Assert($Condition,[string]$Message){if(-not $Condition){throw "TEST FAILED: $Message"}}
function Bytes([string]$Text){return ,([Text.Encoding]::UTF8.GetBytes($Text))}
function Close-Archives{foreach($z in $script:Archives.Values){$z.Dispose()};$script:Archives=@{}}
function Run-Install{try{return Install-Patch}finally{Close-Archives}}
function Run-Restore{try{return Restore-Patch}finally{Close-Archives}}
function Fails($Block){try{& $Block|Out-Null}catch{return};throw 'Expected an error'}
function Read-Text([string]$Name){return [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes((Join-Path $script:Root $Name)))}
$files=@();$zipPath=Join-Path $script:Package 'test.zip'
$zip=[IO.Compression.ZipFile]::Open($zipPath,[IO.Compression.ZipArchiveMode]::Create)
try{
 foreach($name in @('a.txt','b.txt','PcControlCenter.dll')){
  $before=Bytes ('old-'+$name);$after=Bytes ('new-'+$name);[IO.File]::WriteAllBytes((Join-Path $script:Root $name),$before)
  $stream=[IO.MemoryStream]::new();$writer=[IO.BinaryWriter]::new($stream)
  $writer.Write((Bytes "XPRD1`0"));$writer.Write([byte]65);$writer.Write([UInt64]$after.Length);$writer.Write($after);$writer.Write([byte]69);$writer.Flush();$delta=$stream.ToArray()
  $entry=$zip.CreateEntry($name+'.xpd');$entryStream=$entry.Open();$entryStream.Write($delta,0,$delta.Length);$entryStream.Dispose();$writer.Dispose();$stream.Dispose()
  $component='ui';if($name -eq 'PcControlCenter.dll'){$component='camera'}
  $files+=@{path=$name;component=$component;original=(Get-BytesHash $before);patched=(Get-BytesHash $after);size=$after.Length;variants=@(@{source=(Get-BytesHash $before);entry=($name+'.xpd');sha256=(Get-BytesHash $delta)})}
 }
}finally{$zip.Dispose()}
$script:Catalog=@{schema=1;release='1.5';appVersion='5.8.1.130';archive='test.zip';archiveSHA256=(Get-PathHash $zipPath);files=$files}
Assert ((Run-Install) -eq 2) 'install UI only';Assert ((Read-Text 'PcControlCenter.dll') -eq 'old-PcControlCenter.dll') 'camera opt-in'
Assert ((Run-Install) -eq 0) 'idempotency';Assert ((Run-Restore) -eq 2) 'restore';Assert ((Read-Text 'a.txt') -eq 'old-a.txt') 'restored bytes'
[IO.File]::WriteAllBytes((Join-Path $script:Root 'b.txt'),(Bytes 'unknown'));Fails {Run-Install};Assert ((Read-Text 'a.txt') -eq 'old-a.txt') 'unknown source blocks before writing'
[IO.File]::WriteAllBytes((Join-Path $script:Root 'b.txt'),(Bytes 'old-b.txt'))
[IO.File]::WriteAllBytes((Join-Path $script:Root 'PcControlCenter.dll'),(Bytes 'new-PcControlCenter.dll'));$null=Run-Install;$null=Run-Restore
Assert ((Read-Text 'PcControlCenter.dll') -eq 'new-PcControlCenter.dll') 'existing camera fix preserved'
[IO.File]::WriteAllBytes((Join-Path $script:Root 'PcControlCenter.dll'),(Bytes 'old-PcControlCenter.dll'));$CameraFix=$true
Assert ((Run-Install) -eq 3) 'camera selected';Assert ((Run-Restore) -eq 3) 'camera restored';$CameraFix=$false
$script:OriginalAtomic=${function:Write-AtomicBytes};$script:FailOnce=$true
function Write-AtomicBytes([string]$Path,[byte[]]$Bytes){
 if($script:FailOnce -and $Path -eq (Join-Path $script:Root 'b.txt')){$script:FailOnce=$false;throw 'Injected write error'}
 & $script:OriginalAtomic $Path $Bytes
}
Fails {Run-Install};Assert ((Read-Text 'a.txt') -eq 'old-a.txt') 'rollback after partial write';Assert (-not (Test-Path -LiteralPath (Get-StatePath 'pending.json'))) 'journal cleared after successful rollback'
$hash=Get-BytesHash (Bytes 'old-a.txt');Save-Backup $hash (Bytes 'old-a.txt');$targetHash=Get-BytesHash (Bytes 'new-a.txt')
Write-Json (Get-StatePath 'pending.json') @{schema=1;plans=@(@{path='a.txt';before=$hash;after=$targetHash});old=(Convert-State $null)}
[IO.File]::WriteAllBytes((Join-Path $script:Root 'a.txt'),(Bytes 'new-a.txt'));Assert ((Recover-Patch) -eq 1) 'recover';Assert ((Read-Text 'a.txt') -eq 'old-a.txt') 'recovery bytes'
Fails {Get-SafePath $script:Root '../outside'}
$stream=[IO.MemoryStream]::new();$writer=[IO.BinaryWriter]::new($stream);$writer.Write((Bytes "XPRD1`0"));$writer.Write([byte]67);$writer.Write([UInt64]999);$writer.Write([UInt64]2);$writer.Write([byte]69);$writer.Flush();$bad=$stream.ToArray();Fails {Apply-Delta (Bytes 'abc') $bad 2};$writer.Dispose();$stream.Dispose()
Write-Host 'PASS: install, repeat, restore, opt-in camera, preservation, unknown hash, partial-write rollback, crash recovery, path and delta bounds.'
Close-Archives
$newName='ru/PcClipboard.resources.dll';$newPath=Get-SafePath $script:Root $newName;$newBytes=Bytes 'resource-only russian strings'
$stream=[IO.MemoryStream]::new();$writer=[IO.BinaryWriter]::new($stream);$writer.Write((Bytes "XPRD1`0"));$writer.Write([byte]65);$writer.Write([UInt64]$newBytes.Length);$writer.Write($newBytes);$writer.Write([byte]69);$writer.Flush();$delta=$stream.ToArray();$writer.Dispose();$stream.Dispose()
$zip=[IO.Compression.ZipFile]::Open($zipPath,[IO.Compression.ZipArchiveMode]::Update)
try{$entry=$zip.CreateEntry('satellite.xpd');$s=$entry.Open();$s.Write($delta,0,$delta.Length);$s.Dispose()}finally{$zip.Dispose()}
$satellite=@{path=$newName;component='ui';original='ABSENT';patched=(Get-BytesHash $newBytes);size=$newBytes.Length;variants=@(@{source='ABSENT';entry='satellite.xpd';sha256=(Get-BytesHash $delta)})}
$script:Catalog.files=@($satellite)+$files;$script:Catalog.archiveSHA256=Get-PathHash $zipPath
Assert ((Run-Install) -eq 3) 'install new resource file';Assert ((Get-PathHash $newPath) -eq $satellite.patched) 'new file hash'
Assert ((Read-State).schema -eq 2) 'state migrated to schema 2';Assert ((Run-Install) -eq 0) 'new file idempotency'
Assert ((Run-Restore) -eq 3) 'restore removes added file';Assert (-not (Test-Path -LiteralPath $newPath)) 'satellite removed on restore'
[IO.File]::WriteAllBytes($newPath,(Bytes 'unknown satellite'));Fails {Run-Install};Assert ((Get-PathHash $newPath) -eq (Get-BytesHash (Bytes 'unknown satellite'))) 'unknown satellite preserved';[IO.File]::Delete($newPath)
$script:FailOnce=$true;Fails {Run-Install};Assert (-not (Test-Path -LiteralPath $newPath)) 'partial failure removes only created file';Assert ((Read-Text 'a.txt') -eq 'old-a.txt') 'partial failure restores original'
[IO.File]::WriteAllBytes($newPath,$newBytes)
Write-Json (Get-StatePath 'pending.json') @{schema=2;plans=@(@{path=$newName;before='ABSENT';after=$satellite.patched});old=(Convert-State $null)}
Assert ((Recover-Patch) -eq 1) 'recover added file';Assert (-not (Test-Path -LiteralPath $newPath)) 'crash recovery removes added file'
Save-Backup $satellite.patched $newBytes
Write-Json (Get-StatePath 'pending.json') @{schema=2;plans=@(@{path=$newName;before=$satellite.patched;after='ABSENT'});old=(Convert-State $null)}
Assert ((Recover-Patch) -eq 1) 'recover interrupted removal';Assert ((Get-PathHash $newPath) -eq $satellite.patched) 'interrupted removal recovers exact file';[IO.File]::Delete($newPath)
$script:Catalog.guards=@(@{path='a.txt';sha256=(Get-BytesHash (Bytes 'wrong'))});Fails {Run-Install};Assert (-not (Test-Path -LiteralPath $newPath)) 'component guard blocks before file creation';$script:Catalog.guards=@()
Write-Host 'PASS: new satellite creation, rollback deletion, unknown-file preservation, schema migration, crash creation/removal recovery, component guard.'
$resolved=[IO.Path]::GetFullPath($base);$temp=[IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')+'\'
if(-not $resolved.StartsWith($temp,[StringComparison]::OrdinalIgnoreCase)){throw 'Test cleanup path is outside TEMP'}
Remove-Item -LiteralPath $resolved -Recurse -Force
