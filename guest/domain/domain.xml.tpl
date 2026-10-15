<!-- libvirt domain skeleton, rendered by guest/steps/lib/render-domain. What differs between guests
     comes from the profile's `hardware` block, which picks one file per name from fragments/
     (boot, secure_boot, tpm, disk_bus, nic_model, clock, machine), and from the shared SMBIOS
     persona in guest/personas/, so no profile carries its own copy of the vendor strings.

     The hypervisor CPUID bit is disabled and KVM's paravirt state hidden so the guest cannot tell it
     runs under KVM; no <hyperv> enlightenments, which would re-advertise a hypervisor. The persona's
     SMBIOS values, the disk serial and the NIC's MAC OUI are those of real hardware: the patched QEMU
     covers BIOS and ACPI strings but not SMBIOS type 1, 2 and 3. VNC is bound to loopback inside the
     container for guacd only.

     migratable='on' keeps non-migratable CPU features such as invtsc out of the guest: with them,
     libvirt refuses to save guest memory, so no tartarus-clean snapshot could be taken.

     The two optical drives are always present: the first holds the installation medium and the
     second an extra disc (an answer file, a seed) while a guest is being installed; both are empty
     when a guest runs. -->

<domain type='kvm'>
  <name>${name}</name>
  <uuid>${uuid}</uuid>
  <memory unit='KiB'>${ram_kib}</memory>
  <currentMemory unit='KiB'>${ram_kib}</currentMemory>
  <vcpu placement='static'>${vcpus}</vcpu>
  <os>
    <type arch='x86_64' machine='${machine}'>hvm</type>
    ${boot}
    ${boot_order}
    <bootmenu enable='no'/>
    <smbios mode='sysinfo'/>
  </os>
  <features>
    <acpi/>
    <apic/>
    <vmport state='off'/>
    ${secure_boot}
    <kvm>
      <hidden state='on'/>
    </kvm>
  </features>
  <cpu mode='host-passthrough' check='none' migratable='on'>
    <topology sockets='1' dies='1' cores='${vcpus}' threads='1'/>
    <feature policy='disable' name='hypervisor'/>
  </cpu>
  ${clock}
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>restart</on_reboot>
  <on_crash>destroy</on_crash>
  <pm>
    <suspend-to-mem enabled='no'/>
    <suspend-to-disk enabled='no'/>
  </pm>
  ${sysinfo}
  <devices>
    <emulator>/usr/bin/qemu-system-x86_64</emulator>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' discard='unmap'/>
      <source file='${disk}'/>
      ${disk_bus}
      <serial>${disk_serial}</serial>
    </disk>
    <disk type='file' device='cdrom'>
      <driver name='qemu' type='raw'/>
      ${installer_source}
      <target dev='sdb' bus='sata'/>
      <readonly/>
      <address type='drive' controller='0' bus='0' target='0' unit='1'/>
    </disk>
    <disk type='file' device='cdrom'>
      <driver name='qemu' type='raw'/>
      ${extra_source}
      <target dev='sdc' bus='sata'/>
      <readonly/>
      <address type='drive' controller='0' bus='0' target='0' unit='2'/>
    </disk>
    <controller type='sata' index='0'/>
    ${machine_controllers}
    <interface type='network'>
      <mac address='${mac}'/>
      <source network='tt-guest'/>
      ${nic_model}
    </interface>
    ${tpm}
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
