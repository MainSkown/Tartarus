#requires -version 5
<#
  First-logon provisioning of the guest, launched once by the answer file's FirstLogonCommands with
  -Media set to the provisioning CD's drive letter; every other parameter is read from
  provision\parameters.json on that CD. Every step is best-effort and logged to the
  log file inside WorkDir: a failed step is recorded, not retried, so the build report inherits an
  honest list of what went wrong.

  The log is not deleted here because the build fetches it afterwards; cleanup.ps1, run once the
  log is saved, removes it together with the installers. The done marker is written last, so its
  presence means the log is complete.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)] [string] $Media,
  [string] $WorkDir,
  [string] $GuestIp,
  [string] $Gateway = '192.168.150.1',
  [int]    $Prefix  = 24,
  [int]    $Defender,
  [int]    $Decoys,
  [int]    $Sysmon,
  [string] $FirewallRuleName,
  [string] $TaskName,
  [string] $LogName,
  [string] $DoneMarker
)

# Windows 10 silently skips a long RunOnce command, so the parameters do not ride on the command line.
$parametersPath = Join-Path $Media 'provision\parameters.json'
$parameters = Get-Content -LiteralPath $parametersPath -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($parameter in $parameters.PSObject.Properties) {
  Set-Variable -Name $parameter.Name -Value $parameter.Value
}
foreach ($required in 'WorkDir', 'GuestIp', 'Defender', 'Decoys', 'Sysmon', 'FirewallRuleName', 'TaskName', 'LogName', 'DoneMarker') {
  if ($null -eq $parameters.$required) { throw "$parametersPath has no $required" }
}

$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
$log = Join-Path $WorkDir $LogName

function Log([string] $message) {
  $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message
  Add-Content -Path $log -Value $line
  Write-Host $line
}

function Step([string] $name, [scriptblock] $body) {
  Log "STEP $name"
  try {
    $note = & $body
    if ($note) { Log "  ok ($(@($note) -join '; '))" } else { Log '  ok' }
  }
  catch {
    Log "  FAILED: $($_.Exception.Message)"
  }
}

function Set-Reg([string] $path, [string] $key, $value, [string] $type = 'DWord') {
  if (-not (Test-Path $path)) { New-Item -Path $path -Force | Out-Null }
  New-ItemProperty -Path $path -Name $key -Value $value -PropertyType $type -Force | Out-Null
}

Log "provisioning started from $Media into $WorkDir"

Step 'copy payload to the work folder' {
  Copy-Item -Path (Join-Path $Media 'payload\*') -Destination $WorkDir -Recurse -Force
  'copied the agent, python and pillow'
}

Step "static IP $GuestIp/$Prefix, gateway and DNS $Gateway" {
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
  Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False -ErrorAction SilentlyContinue
  New-NetFirewallRule -DisplayName $FirewallRuleName -Direction Inbound -Action Allow `
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

Step 'apply the Defender option (see decision 11; only when Defender is off)' {
  if ($Defender) { return 'Defender stays on, nothing to apply' }
  & (Join-Path $PSScriptRoot 'defender-settings.ps1') -Mode Off
  'settings applied'
}

Step 'install 32-bit Python 3.11' {
  $exe = Join-Path $WorkDir 'python-3.11.9.exe'
  $proc = Start-Process -FilePath $exe -Wait -PassThru -ArgumentList @(
    '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0',
    'Include_launcher=1', 'TargetDir=C:\Python311'
  )
  if ($proc.ExitCode -ne 0) { throw "installer exit code $($proc.ExitCode)" }
  # The analysis agent breaks when the Windows Store python shim in WindowsApps shadows the real one.
  $sys = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $cleaned = ($sys -split ';' | Where-Object { $_ -notmatch 'WindowsApps' }) -join ';'
  [Environment]::SetEnvironmentVariable('Path', $cleaned, 'Machine')
  'installed to C:\Python311'
}

Step 'install Pillow from the offline wheel' {
  $wheel = Get-ChildItem -Path $WorkDir -Filter 'pillow-*.whl' | Select-Object -First 1
  if (-not $wheel) { throw 'wheel not found in payload' }
  & 'C:\Python311\python.exe' -m pip install --no-index --no-warn-script-location $wheel.FullName
  if ($LASTEXITCODE -ne 0) { throw "pip exit code $LASTEXITCODE" }
}

Step 'apply decoys (only when asked)' {
  if (-not $Decoys) { return 'not requested' }
  & (Join-Path $PSScriptRoot 'decoys.ps1')
}

Step 'install Sysmon (only when asked)' {
  if (-not $Sysmon) { return 'not requested' }
  $exe = Join-Path $WorkDir 'Sysmon64.exe'
  $config = Join-Path $PSScriptRoot 'sysmon-config.xml'
  $proc = Start-Process -FilePath $exe -Wait -PassThru -WindowStyle Hidden -ArgumentList @('-accepteula', '-i', $config)
  if ($proc.ExitCode -ne 0) { throw "Sysmon exit code $($proc.ExitCode)" }
  $service = Get-Service -Name Sysmon64 -ErrorAction Stop
  if ($service.Status -ne 'Running') { throw "service is $($service.Status)" }
  $entries = @(Get-WinEvent -LogName 'Microsoft-Windows-Sysmon/Operational' -MaxEvents 5 -ErrorAction Stop)
  if ($entries.Count -eq 0) { throw 'the Sysmon log has no entries' }
  "service $($service.Name) running, $($entries.Count) recent log entries"
}

Step 'register agent.py as a logon scheduled task (highest privileges)' {
  $agent = Join-Path $WorkDir 'agent.py'
  if (-not (Test-Path $agent)) { throw 'agent.py not in payload' }
  $action    = New-ScheduledTaskAction -Execute 'C:\Python311\pythonw.exe' -Argument "`"$agent`""
  $trigger   = New-ScheduledTaskTrigger -AtLogOn
  $principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$env:USERNAME" -RunLevel Highest
  $settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
  Start-ScheduledTask -TaskName $TaskName
  'scheduled and started'
}

Log 'provisioning finished'
New-Item -ItemType File -Force -Path (Join-Path $WorkDir $DoneMarker) | Out-Null
