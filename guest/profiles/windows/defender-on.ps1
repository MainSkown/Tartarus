#requires -version 5
<#
  The reverse of tamper-off.ps1 (decision 15): turns Tamper Protection and real-time protection
  back on for a clone of a Defender-off guest. Idempotent: if both are already on, it does
  nothing and exits 0. Exit codes match tamper-off.ps1: 0 done and verified, 10 the toggle
  control could not be found, 20 verification failed, 30 the removal proof failed. NOT tested on
  a real guest (see decision 15 / S0c "could not verify"); write it exactly to the brief and flag
  that in the notes.
#>
[CmdletBinding()]
param(
  [int] $VerifyWaitSeconds = 3,
  [int] $EicarRemovalWaitSeconds = 30
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes

function Result([string] $key, $value) {
  Write-Output ("RESULT {0}={1}" -f $key, $value)
}

$status = Get-MpComputerStatus
if ($status.IsTamperProtected -and $status.RealTimeProtectionEnabled) {
  Result 'already_on' $true
  exit 0
}

& (Join-Path $PSScriptRoot 'defender-settings.ps1') -Mode On

Start-Process 'windowsdefender://threatsettings'
Start-Sleep -Seconds 2

$root = [Windows.Automation.AutomationElement]::RootElement
$windowCondition = New-Object Windows.Automation.PropertyCondition(
  [Windows.Automation.AutomationElement]::ClassNameProperty, 'Windows.UI.Core.CoreWindow'
)
$securityWindow = $null
for ($attempt = 0; $attempt -lt 10 -and -not $securityWindow; $attempt++) {
  Start-Sleep -Seconds 1
  $candidates = $root.FindAll([Windows.Automation.TreeScope]::Children, $windowCondition)
  foreach ($candidate in $candidates) {
    if ($candidate.Current.Name -match 'Security|Zabezpiecz') { $securityWindow = $candidate }
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
if ($togglePattern.Current.ToggleState -eq [Windows.Automation.ToggleState]::Off) {
  $togglePattern.Toggle()
}
Start-Sleep -Seconds $VerifyWaitSeconds

function Get-TamperProtected { (Get-MpComputerStatus).IsTamperProtected }

$tamperProtected = Get-TamperProtected
if (-not $tamperProtected) {
  Start-Sleep -Seconds $VerifyWaitSeconds
  $tamperProtected = Get-TamperProtected
}
Result 'IsTamperProtected' $tamperProtected
if (-not $tamperProtected) {
  exit 20
}

$realTimeEnabled = (Get-MpComputerStatus).RealTimeProtectionEnabled
if (-not $realTimeEnabled) {
  try { Set-MpPreference -DisableRealtimeMonitoring $false -ErrorAction Stop } catch {}
  Start-Sleep -Seconds $VerifyWaitSeconds
  $realTimeEnabled = (Get-MpComputerStatus).RealTimeProtectionEnabled
}
Result 'RealTimeProtectionEnabled' $realTimeEnabled
if (-not $realTimeEnabled) {
  exit 20
}

$eicarFirstHalf = 'X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTI'
$eicarSecondHalf = 'VIRUS-TEST-FILE!$H+H*'
$eicarPath = Join-Path 'C:\Users\Public' 'sample-check.bin'
Remove-Item -Path $eicarPath -Force -ErrorAction SilentlyContinue
Set-Content -Path $eicarPath -Value ($eicarFirstHalf + $eicarSecondHalf) -NoNewline

$removed = $false
$deadline = (Get-Date).AddSeconds($EicarRemovalWaitSeconds)
while ((Get-Date) -lt $deadline) {
  if (-not (Test-Path $eicarPath)) { $removed = $true; break }
  Start-Sleep -Seconds 1
}
Result 'eicar_removed' $removed
Remove-Item -Path $eicarPath -Force -ErrorAction SilentlyContinue
if (-not $removed) {
  exit 30
}

try { $securityWindow.SetFocus(); [System.Windows.Forms.SendKeys]::SendWait('%{F4}') } catch {}

Result 'done' $true
exit 0
