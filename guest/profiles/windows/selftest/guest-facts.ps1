# Reports what the guest says about itself, one "FACT key=value" line each, for verify-guest.sh
# (and later the wizard's self-test): the surface a watchful sample could read to guess it is
# being observed (SMBIOS, disk and NIC strings, hypervisor bit), plus the TPM, Secure Boot, OS
# build and Defender state. Also runs the
# decision-16 giveaway scan and prints one "GIVEAWAY <where>: <text>" line per hit, so a build with
# a leftover name fails the self-test instead of shipping a guest that looks like what it is.
[CmdletBinding()]
param(
  [string] $TaskName = 'RemoteAssistanceSessionSync',
  [string[]] $SubstringWords = @('tartarus', 'sandbox', 'malware', 'virus', 'cuckoo'),
  [string[]] $TokenWords = @('cape', 'test', 'admin'),
  [string[]] $PrefixWords = @('analy')
)

$ErrorActionPreference = 'SilentlyContinue'
function Fact([string] $key, $value) { Write-Output ("FACT {0}={1}" -f $key, "$value".Trim()) }

$system = Get-CimInstance Win32_ComputerSystem
$bios = Get-CimInstance Win32_BIOS
$board = Get-CimInstance Win32_BaseBoard
$os = Get-CimInstance Win32_OperatingSystem
$version = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'

Fact 'system.manufacturer' $system.Manufacturer
Fact 'system.model' $system.Model
Fact 'bios.vendor' $bios.Manufacturer
Fact 'bios.version' $bios.SMBIOSBIOSVersion
Fact 'bios.serial' $bios.SerialNumber
Fact 'board.manufacturer' $board.Manufacturer
Fact 'board.product' $board.Product
Fact 'disk.model' ((Get-CimInstance Win32_DiskDrive | Select-Object -First 1).Model)
Fact 'cdrom.name' ((Get-CimInstance Win32_CDROMDrive | Select-Object -ExpandProperty Name) -join '; ')
Fact 'nic.name' ((Get-CimInstance Win32_NetworkAdapter -Filter 'PhysicalAdapter=True' | Select-Object -First 1).Name)
Fact 'nic.mac' ((Get-CimInstance Win32_NetworkAdapter -Filter 'PhysicalAdapter=True' | Select-Object -First 1).MACAddress)
Fact 'nic.ipv4' ((Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -ne '127.0.0.1').IPAddress -join ',')
Fact 'video.name' ((Get-CimInstance Win32_VideoController | Select-Object -First 1).Name)
Fact 'cpu.name' ((Get-CimInstance Win32_Processor | Select-Object -First 1).Name)
Fact 'cpu.hypervisor_present' $system.HypervisorPresent
Fact 'tpm.present' ((Get-Tpm).TpmPresent)
Fact 'tpm.spec_version' ((Get-CimInstance -Namespace root/cimv2/Security/MicrosoftTpm Win32_Tpm).SpecVersion)
Fact 'secureboot.enabled' (Confirm-SecureBootUEFI)
Fact 'os.caption' $os.Caption
Fact 'os.build' ("{0}.{1}" -f $version.CurrentBuild, $version.UBR)
Fact 'os.display_version' $version.DisplayVersion
Fact 'os.ui_language' ((Get-UICulture).Name)
Fact 'os.hostname' $env:COMPUTERNAME
Fact 'os.user' $env:USERNAME
$defender = Get-MpComputerStatus
Fact 'defender.antivirus_enabled' $defender.AntivirusEnabled
Fact 'defender.realtime_enabled' $defender.RealTimeProtectionEnabled
Fact 'defender.tamper_protected' $defender.IsTamperProtected
Fact 'firewall.enabled_profiles' ((Get-NetFirewallProfile | Where-Object Enabled).Name -join ',')
Fact 'uac.enable_lua' ((Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System').EnableLUA)
Fact 'wuauserv.start_type' ((Get-Service wuauserv).StartType)
Fact 'python.version_bits' (& 'C:\Python311\python.exe' -c 'import platform,struct; print(platform.python_version(), struct.calcsize(''P'')*8)')
Fact 'python.pillow' (& 'C:\Python311\python.exe' -c 'import PIL; print(PIL.__version__)')
Fact 'agent.task' ((Get-ScheduledTask -TaskName $TaskName).State)

# --- decision 16: nothing in the guest says what the machine is ----------------------------------

# Legitimate system names that happen to contain one of the short, part-of-a-word tokens: the
# built-in Administrator account (not "admin" as a whole word) and AdminSDHolder-style service
# accounts Windows itself creates. The scan below never widens this list, it only shortens the
# set of candidates already allowed through by whole-token matching.
$AllowedTokenHits = @('Administrator', 'AdministratorAccount')

function Split-Tokens([string] $text) {
  # Same rule as guest_engine.giveaways.tokens: split on non-alphanumerics and camel-case, so a
  # short TokenWords entry inside an ordinary English word never matches by accident.
  [regex]::Matches($text, '[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+') | ForEach-Object { $_.Value.ToLower() }
}

function Find-Giveaway([string] $text) {
  if ([string]::IsNullOrWhiteSpace($text)) { return $null }
  $lowered = $text.ToLower()
  foreach ($word in $SubstringWords) {
    if ($lowered.Contains($word)) { return $word }
  }
  $tokens = Split-Tokens $text
  foreach ($token in $tokens) {
    if ($TokenWords -contains $token) { return $token }
    foreach ($prefix in $PrefixWords) {
      if ($token.StartsWith($prefix)) { return $prefix }
    }
  }
  return $null
}

function Report-Giveaway([string] $where, [string] $text) {
  if ($AllowedTokenHits -contains $text) { return }
  $hit = Find-Giveaway $text
  if ($hit) { Write-Output ("GIVEAWAY {0}: {1}" -f $where, $text) }
}

Report-Giveaway 'computer name' $env:COMPUTERNAME

foreach ($account in Get-LocalUser) {
  Report-Giveaway 'local account' $account.Name
}

foreach ($task in Get-ScheduledTask | Where-Object { $_.TaskPath -notlike '\Microsoft\*' }) {
  Report-Giveaway 'scheduled task' $task.TaskName
}

foreach ($service in Get-Service) {
  Report-Giveaway 'service' $service.DisplayName
}

foreach ($rule in Get-NetFirewallRule -PolicyStore ActiveStore -ErrorAction SilentlyContinue) {
  Report-Giveaway 'firewall rule' $rule.DisplayName
}

foreach ($hive in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run', 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run')) {
  $entry = Get-ItemProperty -Path $hive -ErrorAction SilentlyContinue
  if ($entry) {
    foreach ($name in $entry.PSObject.Properties.Name | Where-Object { $_ -notmatch '^PS' }) {
      Report-Giveaway "Run key $hive" $name
    }
  }
}

foreach ($root in @('C:\', 'C:\ProgramData', "C:\Users")) {
  Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    Report-Giveaway "folder under $root" $_.Name
  }
}

$uninstallPaths = @(
  'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
foreach ($path in $uninstallPaths) {
  Get-ItemProperty -Path $path -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.DisplayName) { Report-Giveaway 'installed program' $_.DisplayName }
  }
}
