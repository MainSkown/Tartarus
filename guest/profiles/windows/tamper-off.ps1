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
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes

function Result([string] $key, $value) {
  Write-Output ("RESULT {0}={1}" -f $key, $value)
}

# Step 1: policy keys, before Tamper Protection is touched (decision 11).
& (Join-Path $PSScriptRoot 'defender-settings.ps1') -Mode Off

# Step 2: open the page outside any monitored analysis, where Windows Security can draw a window.
Start-Process 'windowsdefender://threatsettings'
Start-Sleep -Seconds 2

$root = [Windows.Automation.AutomationElement]::RootElement
$AppTitles = @('Zabezpieczenia Windows', 'Windows Security')
$frameCondition = New-Object Windows.Automation.PropertyCondition(
  [Windows.Automation.AutomationElement]::ClassNameProperty, 'ApplicationFrameWindow'
)
$securityWindow = $null
for ($attempt = 0; $attempt -lt 10 -and -not $securityWindow; $attempt++) {
  Start-Sleep -Seconds 1
  $frames = $root.FindAll([Windows.Automation.TreeScope]::Children, $frameCondition)
  foreach ($frame in $frames) {
    if ($AppTitles -contains $frame.Current.Name) { $securityWindow = $frame }
  }
}
if (-not $securityWindow) {
  Result 'window' 'not-found'
  exit 10
}

$KnownNames = @('Ochrona przed naruszeniami', 'Ochrona przed manipulacją', 'Tamper Protection')
$toggleCondition = New-Object Windows.Automation.PropertyCondition(
  [Windows.Automation.AutomationElement]::AutomationIdProperty, 'settingToggle'
)
$toggles = @($securityWindow.FindAll([Windows.Automation.TreeScope]::Descendants, $toggleCondition))

$tamperToggle = $toggles | Where-Object { $KnownNames -contains $_.Current.Name } | Select-Object -First 1
if (-not $tamperToggle -and $toggles.Count -ge 5) {
  $tamperToggle = $toggles[4]
}
if (-not $tamperToggle) {
  Result 'toggle' 'not-found'
  exit 10
}
Result 'toggle_name' $tamperToggle.Current.Name

$togglePattern = $tamperToggle.GetCurrentPattern([Windows.Automation.TogglePattern]::Pattern)
if ($togglePattern.Current.ToggleState -eq [Windows.Automation.ToggleState]::On) {
  $togglePattern.Toggle()
}
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

try { $securityWindow.SetFocus(); [System.Windows.Forms.SendKeys]::SendWait('%{F4}') } catch {}

Result 'done' $true
exit 0
