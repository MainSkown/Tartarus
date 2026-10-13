#requires -version 5
<#
  First-logon provisioning for the Tartarus analysis guest, launched once by autounattend.xml's
  FirstLogonCommands with -Media set to the provisioning CD's drive letter. Every step is
  best-effort and logged with its outcome to C:\tartarus\provision.log: a step that cannot be
  scripted (Tamper Protection is the expected one) is recorded, not worked around, so the build
  report and the M6 wizard inherit an honest list of what still needs a human.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)] [string] $Media,
  [string] $GuestIp = '192.168.150.10',
  [string] $Gateway = '192.168.150.1',
  [int]    $Prefix  = 24
)

$ErrorActionPreference = 'Continue'
$root = 'C:\tartarus'
New-Item -ItemType Directory -Force -Path $root | Out-Null
$log = Join-Path $root 'provision.log'

function Log([string] $message) {
  $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message
  Add-Content -Path $log -Value $line
  Write-Host $line
}

# Runs one named provisioning step and records scripted / caveat / failed, never aborting the run.
function Step([string] $name, [scriptblock] $body) {
  Log "STEP $name"
  try {
    $note = & $body
    if ($note) { Log "  ok ($note)" } else { Log '  ok' }
  }
  catch {
    Log "  FAILED: $($_.Exception.Message)"
  }
}

function Set-Reg([string] $path, [string] $key, $value, [string] $type = 'DWord') {
  if (-not (Test-Path $path)) { New-Item -Path $path -Force | Out-Null }
  New-ItemProperty -Path $path -Name $key -Value $value -PropertyType $type -Force | Out-Null
}

Log "provisioning started from $Media"

Step 'copy payload to C:\tartarus' {
  Copy-Item -Path (Join-Path $Media 'payload\*') -Destination $root -Recurse -Force
  'copied agent.py, python and pillow'
}

Step 'static IP 192.168.150.10/24, gateway and DNS .1' {
  $adapter = Get-NetAdapter -Physical | Where-Object Status -ne 'Disabled' | Select-Object -First 1
  if (-not $adapter) { throw 'no network adapter found' }
  Remove-NetIPAddress -InterfaceIndex $adapter.ifIndex -Confirm:$false -ErrorAction SilentlyContinue
  Remove-NetRoute -InterfaceIndex $adapter.ifIndex -Confirm:$false -ErrorAction SilentlyContinue
  New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress $GuestIp -PrefixLength $Prefix -DefaultGateway $Gateway | Out-Null
  Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -ServerAddresses $Gateway
  "adapter '$($adapter.Name)' set to $GuestIp"
}

Step 'disable Windows Update' {
  Set-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU' 'NoAutoUpdate' 1
  Set-Service -Name wuauserv -StartupType Disabled -ErrorAction SilentlyContinue
  Stop-Service -Name wuauserv -Force -ErrorAction SilentlyContinue
}

Step 'disable UAC prompts' {
  Set-Reg 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' 'EnableLUA' 0
  Set-Reg 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' 'ConsentPromptBehaviorAdmin' 0
  Set-Reg 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' 'PromptOnSecureDesktop' 0
}

Step 'disable the firewall and open port 8000' {
  # Both: the firewall is off for the sandbox, and a rule survives if a profile is re-enabled.
  Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False -ErrorAction SilentlyContinue
  New-NetFirewallRule -DisplayName 'Tartarus agent' -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort 8000 -ErrorAction SilentlyContinue | Out-Null
}

Step 'disable telemetry' {
  Set-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\DataCollection' 'AllowTelemetry' 0
  Set-Service -Name DiagTrack -StartupType Disabled -ErrorAction SilentlyContinue
  Stop-Service -Name DiagTrack -Force -ErrorAction SilentlyContinue
}

Step 'disable sleep and hibernate' {
  powercfg /change standby-timeout-ac 0
  powercfg /change standby-timeout-dc 0
  powercfg /change monitor-timeout-ac 0
  powercfg /hibernate off
}

Step 'disable SmartScreen' {
  Set-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\System' 'EnableSmartScreen' 0
  Set-Reg 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer' 'SmartScreenEnabled' 'Off' 'String'
}

# Defender and Tamper Protection: try the documented, supported settings only. Tamper Protection,
# on by default, blocks a scripted disable of Defender itself and cannot be turned off by registry
# or Set-MpPreference once active; open question 5 in tartarus-v1. Record exactly what held.
Step 'disable Defender (policy + Set-MpPreference, best effort)' {
  $notes = @()
  Set-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender' 'DisableAntiSpyware' 1
  Set-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender\Real-Time Protection' 'DisableRealtimeMonitoring' 1
  Set-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender\Real-Time Protection' 'DisableBehaviorMonitoring' 1
  try {
    Set-MpPreference -DisableRealtimeMonitoring $true -ErrorAction Stop
    $notes += 'Set-MpPreference accepted'
  } catch {
    $notes += 'Set-MpPreference blocked (Tamper Protection likely on)'
  }
  try {
    $tp = (Get-MpComputerStatus -ErrorAction Stop).IsTamperProtected
    $rt = (Get-MpComputerStatus -ErrorAction Stop).RealTimeProtectionEnabled
    $notes += "TamperProtection=$tp RealTimeProtection=$rt"
  } catch {
    $notes += 'Get-MpComputerStatus unavailable'
  }
  ($notes -join '; ')
}

Step 'install 32-bit Python 3.11' {
  $exe = Join-Path $root 'python-3.11.9.exe'
  $proc = Start-Process -FilePath $exe -Wait -PassThru -ArgumentList @(
    '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0',
    'Include_launcher=1', 'TargetDir=C:\Python311'
  )
  if ($proc.ExitCode -ne 0) { throw "installer exit code $($proc.ExitCode)" }
  # CAPE's analyzer breaks when the Windows Store python shim in WindowsApps shadows the real one.
  $sys = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $cleaned = ($sys -split ';' | Where-Object { $_ -notmatch 'WindowsApps' }) -join ';'
  [Environment]::SetEnvironmentVariable('Path', $cleaned, 'Machine')
  'installed to C:\Python311'
}

Step 'install Pillow from the offline wheel' {
  $wheel = Get-ChildItem -Path $root -Filter 'pillow-*.whl' | Select-Object -First 1
  if (-not $wheel) { throw 'wheel not found in payload' }
  & 'C:\Python311\python.exe' -m pip install --no-index --no-warn-script-location $wheel.FullName
  if ($LASTEXITCODE -ne 0) { throw "pip exit code $LASTEXITCODE" }
}

Step 'register CAPE agent.py as a logon scheduled task (highest privileges)' {
  $agent = Join-Path $root 'agent.py'
  if (-not (Test-Path $agent)) { throw 'agent.py not in payload' }
  $action    = New-ScheduledTaskAction -Execute 'C:\Python311\pythonw.exe' -Argument "`"$agent`""
  $trigger   = New-ScheduledTaskTrigger -AtLogOn
  $principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$env:USERNAME" -RunLevel Highest
  $settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName 'CAPE Agent' -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
  # Start it now so the build can reach :8000 without a reboot.
  Start-ScheduledTask -TaskName 'CAPE Agent'
  'scheduled and started'
}

Log 'provisioning finished'
New-Item -ItemType File -Force -Path (Join-Path $root 'provision.done') | Out-Null
