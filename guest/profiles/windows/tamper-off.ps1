#requires -version 5
<#
  Implements decision 11's step list, in order, through the 64-bit PowerShell. Exit codes:
  0 done and verified, 10 the toggle control could not be found (host step pauses for the manual
  fallback), 20 verification failed, 30 a proof step failed. Each check prints one
  "RESULT key=value" line so the host step can log it.
#>
[CmdletBinding()]
param(
  [int] $VerifyWaitSeconds = 3,
  [int] $EicarWaitSeconds = 12
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'security-ui.ps1')

function Result([string] $key, $value) {
  Write-Output ("RESULT {0}={1}" -f $key, $value)
}

# Step 1: policy keys, before Tamper Protection is touched (decision 11).
& (Join-Path $PSScriptRoot 'defender-settings.ps1') -Mode Off

# Step 2: open the page outside any monitored analysis, where Windows Security can draw a window.
$securityWindow = Open-SecurityWindow
if (-not $securityWindow) {
  Result 'window' 'not-found'
  exit 10
}

$tamperToggle = Find-TamperToggle $securityWindow
if (-not $tamperToggle) {
  Result 'toggle' 'not-found'
  exit 10
}
Result 'toggle_name' $tamperToggle.Current.Name

Set-ToggleState $tamperToggle $false
Start-Sleep -Seconds $VerifyWaitSeconds

function Get-TamperProtected { (Get-MpComputerStatus).IsTamperProtected }

$tamperProtected = Get-TamperProtected
if ($tamperProtected) {
  Start-Sleep -Seconds $VerifyWaitSeconds
  $tamperProtected = Get-TamperProtected
}
Result 'IsTamperProtected' $tamperProtected
if ($tamperProtected) {
  exit 20
}

$realTimeEnabled = (Get-MpComputerStatus).RealTimeProtectionEnabled
if ($realTimeEnabled) {
  & (Join-Path $PSScriptRoot 'defender-settings.ps1') -Mode Off
  try { Set-MpPreference -DisableRealtimeMonitoring $true -ErrorAction Stop } catch {}
  Start-Sleep -Seconds $VerifyWaitSeconds
  $realTimeEnabled = (Get-MpComputerStatus).RealTimeProtectionEnabled
}
Result 'RealTimeProtectionEnabled' $realTimeEnabled
if ($realTimeEnabled) {
  exit 20
}

$eicarFirstHalf = 'X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTI'
$eicarSecondHalf = 'VIRUS-TEST-FILE!$H+H*'
$eicarPath = Join-Path 'C:\Users\Public' 'sample-check.bin'
Set-Content -Path $eicarPath -Value ($eicarFirstHalf + $eicarSecondHalf) -NoNewline
Start-Sleep -Seconds $EicarWaitSeconds
$presentAfterWrite = Test-Path $eicarPath
Result 'eicar_present_after_write' $presentAfterWrite
if (-not $presentAfterWrite) {
  exit 30
}

Start-MpScan -ScanType CustomScan -ScanPath (Split-Path $eicarPath) -ErrorAction SilentlyContinue
$presentAfterScan = Test-Path $eicarPath
Result 'eicar_present_after_scan' $presentAfterScan
Remove-Item -Path $eicarPath -Force -ErrorAction SilentlyContinue
if (-not $presentAfterScan) {
  exit 30
}

Close-SecurityWindow $securityWindow

Result 'done' $true
exit 0
