#requires -version 5
<#
  Gives the account's profile the look of a machine that has been used for a while: a handful of
  documents, downloads, pictures and desktop shortcuts with dates spread over the past months, and
  a small Recent-items trail. Idempotent (a marker file skips a second run); no network access;
  every action is best-effort and logged, the same pattern as provision.ps1's Step helper.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$profileRoot = [Environment]::GetFolderPath('UserProfile')
$marker = Join-Path $profileRoot '.decoys-applied'

if (Test-Path $marker) {
  Write-Output 'RESULT decoys=already-applied'
  return
}

function Log([string] $message) { Write-Output "RESULT $message" }

function Step([string] $name, [scriptblock] $body) {
  try { & $body; Log "$name=ok" }
  catch { Log "$name=failed ($($_.Exception.Message))" }
}

function Past-Date([int] $daysAgo) { (Get-Date).AddDays(-$daysAgo) }

function Write-Dated([string] $path, [string] $content, [int] $daysAgo) {
  Set-Content -Path $path -Value $content -Encoding UTF8
  $when = Past-Date $daysAgo
  (Get-Item $path).CreationTime = $when
  (Get-Item $path).LastWriteTime = $when
}

$documents = Join-Path $profileRoot 'Documents'
$downloads = Join-Path $profileRoot 'Downloads'
$pictures  = Join-Path $profileRoot 'Pictures'
$desktop   = Join-Path $profileRoot 'Desktop'
$recent    = Join-Path $profileRoot 'AppData\Roaming\Microsoft\Windows\Recent'

Step 'documents' {
  New-Item -ItemType Directory -Force -Path $documents | Out-Null
  Write-Dated (Join-Path $documents 'Notes.txt') "Shopping list`r`nMilk, bread, coffee`r`nCall the plumber" 118
  Write-Dated (Join-Path $documents 'Budget.csv') "Month,Amount`r`nJanuary,1200`r`nFebruary,980" 74
  Write-Dated (Join-Path $documents 'Letter.txt') "Dear Sir or Madam,`r`n`r`nThank you for your reply." 31
}

Step 'downloads' {
  New-Item -ItemType Directory -Force -Path $downloads | Out-Null
  Write-Dated (Join-Path $downloads 'readme.txt') 'Installation notes for the printer driver.' 52
  Write-Dated (Join-Path $downloads 'invoice_2043.txt') 'Invoice #2043 - paid' 20
}

Step 'pictures placeholders' {
  New-Item -ItemType Directory -Force -Path $pictures | Out-Null
  foreach ($name in @('IMG_2041.txt', 'IMG_2098.txt', 'Screenshot_1.txt')) {
    Write-Dated (Join-Path $pictures $name) 'placeholder' (Get-Random -Minimum 10 -Maximum 150)
  }
}

Step 'desktop shortcuts' {
  New-Item -ItemType Directory -Force -Path $desktop | Out-Null
  $shell = New-Object -ComObject WScript.Shell
  $shortcut = $shell.CreateShortcut((Join-Path $desktop 'Notes.lnk'))
  $shortcut.TargetPath = Join-Path $documents 'Notes.txt'
  $shortcut.Save()
  (Get-Item (Join-Path $desktop 'Notes.lnk')).CreationTime = Past-Date 90
}

Step 'recent items trail' {
  New-Item -ItemType Directory -Force -Path $recent | Out-Null
  $shell = New-Object -ComObject WScript.Shell
  foreach ($target in @((Join-Path $documents 'Budget.csv'), (Join-Path $downloads 'readme.txt'))) {
    $name = [IO.Path]::GetFileNameWithoutExtension($target)
    $link = $shell.CreateShortcut((Join-Path $recent "$name.lnk"))
    $link.TargetPath = $target
    $link.Save()
  }
}

New-Item -ItemType File -Force -Path $marker | Out-Null
Log 'decoys=applied'
