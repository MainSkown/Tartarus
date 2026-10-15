#requires -version 5
<#
  Writes or removes the Defender policy keys of decision 11 step 1. Idempotent: -Force on every
  write, and -Mode On simply removes whatever keys -Mode Off would have written. Called by
  provision.ps1 (-Mode Off, before Tamper Protection is ever touched) and by tamper-off.ps1 /
  defender-on.ps1 (through the 64-bit PowerShell, after Tamper Protection has been toggled).
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)] [ValidateSet('Off', 'On')] [string] $Mode
)

$ErrorActionPreference = 'Continue'

$RealTimePath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender\Real-Time Protection'
$DefenderPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender'
$ReportingPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender\Spynet'

function Set-Reg([string] $path, [string] $key, $value, [string] $type = 'DWord') {
  if (-not (Test-Path $path)) { New-Item -Path $path -Force | Out-Null }
  New-ItemProperty -Path $path -Name $key -Value $value -PropertyType $type -Force | Out-Null
}

function Remove-Reg([string] $path, [string] $key) {
  if (Test-Path $path) {
    Remove-ItemProperty -Path $path -Name $key -Force -ErrorAction SilentlyContinue
  }
}

$keys = @(
  @{ Path = $RealTimePath;  Name = 'DisableRealtimeMonitoring'; Value = 1 },
  @{ Path = $RealTimePath;  Name = 'DisableBehaviorMonitoring'; Value = 1 },
  @{ Path = $RealTimePath;  Name = 'DisableOnAccessProtection'; Value = 1 },
  @{ Path = $RealTimePath;  Name = 'DisableIOAVProtection';     Value = 1 },
  @{ Path = $DefenderPath;  Name = 'DisableScriptScanning';     Value = 1 },
  @{ Path = $ReportingPath; Name = 'SpynetReporting';           Value = 0 },
  @{ Path = $ReportingPath; Name = 'SubmitSamplesConsent';      Value = 2 }
)

if ($Mode -eq 'Off') {
  foreach ($entry in $keys) { Set-Reg $entry.Path $entry.Name $entry.Value }
  Write-Output 'RESULT policy_keys=written'
}
else {
  foreach ($entry in $keys) { Remove-Reg $entry.Path $entry.Name }
  Write-Output 'RESULT policy_keys=removed'
}
