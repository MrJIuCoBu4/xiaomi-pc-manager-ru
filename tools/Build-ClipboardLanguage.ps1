[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
$output=[IO.Path]::GetFullPath($OutputDirectory)
[IO.Directory]::CreateDirectory($output)|Out-Null
$resource=Join-Path $output 'PcClipboard.Properties.Resources.ru.resources'
$writer=[Resources.ResourceWriter]::new($resource)
try{
 foreach($line in [IO.File]::ReadAllLines((Join-Path $PSScriptRoot '../translations/clipboard.tsv'),[Text.Encoding]::UTF8)){
  if(-not $line){continue};$tab=$line.IndexOf("`t");if($tab -lt 1){throw 'Invalid translation row'}
  $writer.AddResource($line.Substring(0,$tab),$line.Substring($tab+1))
 }
}finally{$writer.Dispose()}
$culture=Join-Path $output 'ru';[IO.Directory]::CreateDirectory($culture)|Out-Null
$compiler=Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if(-not (Test-Path -LiteralPath $compiler)){throw 'Windows .NET Framework C# compiler not found'}
& $compiler /nologo /target:library "/out:$culture/PcClipboard.resources.dll" "/resource:$resource" (Join-Path $PSScriptRoot 'ClipboardSatellite.cs')
if($LASTEXITCODE -ne 0){throw 'Resource assembly build failed'}
Write-Host "Built: $culture/PcClipboard.resources.dll"
