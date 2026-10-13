# Reports what the guest says about itself, one "FACT key=value" line each, for verify-guest.sh
# (and later the wizard's self-test): the sandbox-detection surface (SMBIOS, disk and NIC
# strings, hypervisor bit) plus the TPM, Secure Boot, OS build and Defender state.
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
Fact 'agent.task' ((Get-ScheduledTask -TaskName 'CAPE Agent').State)
