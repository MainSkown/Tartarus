#requires -version 5
<#
  Gives a cloned guest its own identity, in three phases the host step calls through the agent's
  64-bit PowerShell (the host passes every value as quoted text):

    Report   prints the facts the host compares, as "RESULT key=value" lines, and changes nothing.
    Apply    sets the static address, the computer name, a fresh MachineGuid, the decoys when asked
             for, clears the event logs, and reboots. It runs asynchronously, because changing the
             address ends the agent's connection, so what it did is written to a log beside the
             script, ending with the line "rebooting <Token>" just before the restart.
    Discard  removes that log once the host has read it.

  Each Apply step is best-effort and logged; the host verifies the outcome with Report afterwards.
  The computer name takes effect only after the reboot, which is why Apply ends with one.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)] [ValidateSet('Report', 'Apply', 'Discard')] [string] $Phase,
  [string] $LogName = '',
  [string] $MachineName = '',
  [string] $GuestIp = '',
  [string] $Gateway = '',
  [int]    $Prefix = 24,
  [string] $Decoys = 'false',
  [string] $Token = ''
)

$ErrorActionPreference = 'Continue'
$CryptographyKey = 'HKLM:\SOFTWARE\Microsoft\Cryptography'
$log = Join-Path $PSScriptRoot $LogName

function Result([string] $key, $value) {
  Write-Output ('RESULT {0}={1}' -f $key, $value)
}

function Log([string] $message) {
  Add-Content -Path $log -Value ('{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message)
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

# A link-local address is what Windows invents while it waits for DHCP; it is not the guest's.
function Get-HeldAddresses($adapter) {
  Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '169.254.*' }
}

function Show-Identity {
  $adapter = Get-NetAdapter -Physical | Where-Object Status -ne 'Disabled' | Select-Object -First 1
  $addresses = @(Get-HeldAddresses $adapter | ForEach-Object { $_.IPAddress })
  Result 'hostname' $env:COMPUTERNAME
  Result 'ip' ($addresses -join ',')
  Result 'machine_guid' (Get-ItemProperty -Path $CryptographyKey -Name MachineGuid).MachineGuid
  Result 'boot_time' ((Get-CimInstance -ClassName Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o'))
}

function Apply-Identity {
  Set-Content -Path $log -Value ''
  Log "reconfiguring as $MachineName at $GuestIp"

  Step "static IP $GuestIp/$Prefix, gateway and DNS $Gateway" {
    $adapter = Get-NetAdapter -Physical | Where-Object Status -ne 'Disabled' | Select-Object -First 1
    if (-not $adapter) { throw 'no network adapter found' }
    $held = @(Get-HeldAddresses $adapter)
    if ($held.Count -eq 1 -and $held[0].IPAddress -eq $GuestIp -and $held[0].PrefixOrigin -eq 'Manual') {
      return "adapter '$($adapter.Name)' already has $GuestIp"
    }
    Remove-NetIPAddress -InterfaceIndex $adapter.ifIndex -Confirm:$false -ErrorAction SilentlyContinue
    Remove-NetRoute -InterfaceIndex $adapter.ifIndex -Confirm:$false -ErrorAction SilentlyContinue
    New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress $GuestIp -PrefixLength $Prefix -DefaultGateway $Gateway -ErrorAction Stop | Out-Null
    Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -ServerAddresses $Gateway -ErrorAction Stop
    "adapter '$($adapter.Name)' set to $GuestIp"
  }

  Step "computer name $MachineName" {
    if ($env:COMPUTERNAME -eq $MachineName) { return 'already has that name' }
    Rename-Computer -NewName $MachineName -Force -ErrorAction Stop
  }

  Step 'MachineGuid' {
    $fresh = [guid]::NewGuid().ToString()
    Set-ItemProperty -Path $CryptographyKey -Name MachineGuid -Value $fresh -ErrorAction Stop
    "now $fresh"
  }

  Step 'decoys (only when asked)' {
    if ($Decoys -ne 'true') { return 'not requested' }
    & (Join-Path $PSScriptRoot 'decoys.ps1')
  }

  Step 'clear the event logs' {
    $names = @(& wevtutil.exe el)
    foreach ($name in $names) { & wevtutil.exe cl $name 2>$null }
    "$($names.Count) logs"
  }

  Log "rebooting $Token"
  Restart-Computer -Force
}

function Discard-Log {
  Remove-Item -Path $log -Force -ErrorAction SilentlyContinue
}

switch ($Phase) {
  'Report' { Show-Identity }
  'Apply' { Apply-Identity }
  'Discard' { Discard-Log }
}
exit 0
