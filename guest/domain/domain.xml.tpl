<!-- libvirt domain for the Windows guest, rendered by scripts/build-guest.sh with envsubst.
     Q35 + UEFI Secure Boot (Microsoft-enrolled OVMF vars) + emulated TPM 2.0, so Windows 11
     installs without a hardware-check bypass. The hypervisor CPUID bit is disabled and KVM's
     paravirt state hidden so the guest cannot tell it runs under KVM; no <hyperv> enlightenments,
     which would re-advertise a hypervisor. SMBIOS, disk serial and the NIC's MAC OUI are set to
     real Dell values, closing the SMBIOS finding from M0a (the patched QEMU covers BIOS/ACPI but
     not SMBIOS type1/2/3). VNC is bound to loopback inside the container for guacd only.
     migratable='on' keeps non-migratable CPU features such as invtsc out of the guest: with them,
     libvirt refuses to save guest memory, so no tartarus-clean snapshot could be taken. -->

<domain type='kvm'>
  <name>${GUEST_NAME}</name>
  <uuid>${GUEST_UUID}</uuid>
  <memory unit='KiB'>${GUEST_RAM_KIB}</memory>
  <currentMemory unit='KiB'>${GUEST_RAM_KIB}</currentMemory>
  <vcpu placement='static'>${GUEST_VCPUS}</vcpu>
  <os>
    <type arch='x86_64' machine='q35'>hvm</type>
    <loader readonly='yes' secure='yes' type='pflash'>${OVMF_CODE}</loader>
    <nvram template='${OVMF_VARS}'>${GUEST_NVRAM}</nvram>
    ${OS_BOOT}
    <bootmenu enable='no'/>
    <smbios mode='sysinfo'/>
  </os>
  <features>
    <acpi/>
    <apic/>
    <vmport state='off'/>
    <smm state='on'/>
    <kvm>
      <hidden state='on'/>
    </kvm>
  </features>
  <cpu mode='host-passthrough' check='none' migratable='on'>
    <topology sockets='1' dies='1' cores='${GUEST_VCPUS}' threads='1'/>
    <feature policy='disable' name='hypervisor'/>
  </cpu>
  <clock offset='localtime'>
    <timer name='rtc' tickpolicy='catchup'/>
    <timer name='pit' tickpolicy='delay'/>
    <timer name='hpet' present='no'/>
  </clock>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>restart</on_reboot>
  <on_crash>destroy</on_crash>
  <pm>
    <suspend-to-mem enabled='no'/>
    <suspend-to-disk enabled='no'/>
  </pm>
  <sysinfo type='smbios'>
    <bios>
      <entry name='vendor'>Dell Inc.</entry>
      <entry name='version'>2.18.0</entry>
      <entry name='date'>07/14/2024</entry>
    </bios>
    <system>
      <entry name='manufacturer'>Dell Inc.</entry>
      <entry name='product'>OptiPlex 7090</entry>
      <entry name='version'>Not Specified</entry>
      <entry name='serial'>${SMBIOS_SERIAL}</entry>
      <entry name='uuid'>${GUEST_UUID}</entry>
      <entry name='sku'>0A26</entry>
      <entry name='family'>OptiPlex</entry>
    </system>
    <baseBoard>
      <entry name='manufacturer'>Dell Inc.</entry>
      <entry name='product'>0K240Y</entry>
      <entry name='version'>A01</entry>
      <entry name='serial'>${SMBIOS_BOARD_SERIAL}</entry>
    </baseBoard>
    <chassis>
      <entry name='manufacturer'>Dell Inc.</entry>
      <entry name='version'>Not Specified</entry>
      <entry name='serial'>${SMBIOS_SERIAL}</entry>
      <entry name='asset'>Not Specified</entry>
      <entry name='sku'>Desktop</entry>
    </chassis>
    <oemStrings>
      <entry>Dell System</entry>
      <entry>1[0A26]</entry>
    </oemStrings>
  </sysinfo>
  <devices>
    <emulator>/usr/bin/qemu-system-x86_64</emulator>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' discard='unmap'/>
      <source file='${GUEST_DISK}'/>
      <target dev='sda' bus='sata'/>
      <serial>${SMBIOS_DISK_SERIAL}</serial>
      <address type='drive' controller='0' bus='0' target='0' unit='0'/>
    </disk>
    <disk type='file' device='cdrom'>
      <driver name='qemu' type='raw'/>
      ${INSTALL_CDROM_SOURCE}
      <target dev='sdb' bus='sata'/>
      <readonly/>
      <address type='drive' controller='0' bus='0' target='0' unit='1'/>
    </disk>
    <disk type='file' device='cdrom'>
      <driver name='qemu' type='raw'/>
      ${UNATTEND_CDROM_SOURCE}
      <target dev='sdc' bus='sata'/>
      <readonly/>
      <address type='drive' controller='0' bus='0' target='0' unit='2'/>
    </disk>
    <controller type='sata' index='0'/>
    <controller type='pci' model='pcie-root'/>
    <controller type='pci' model='pcie-root-port'/>
    <controller type='pci' model='pcie-root-port'/>
    <controller type='pci' model='pcie-root-port'/>
    <controller type='pci' model='pcie-root-port'/>
    <interface type='network'>
      <mac address='${GUEST_MAC}'/>
      <source network='tt-guest'/>
      <model type='e1000e'/>
    </interface>
    <tpm model='tpm-crb'>
      <backend type='emulator' version='2.0'/>
    </tpm>
    <input type='tablet' bus='usb'/>
    <input type='mouse' bus='ps2'/>
    <input type='keyboard' bus='ps2'/>
    <graphics type='vnc' port='-1' autoport='yes' listen='127.0.0.1'/>
    <video>
      <model type='vga' vram='16384' heads='1'/>
    </video>
    <memballoon model='none'/>
  </devices>
</domain>
