const MIB = 1024 ** 2
const GIB = 1024 ** 3

/** The first bytes a capture or memory image starts with, the same magics the app and backend sniff for. */
const PCAP_HEAD = Buffer.from([0xa1, 0xb2, 0xc3, 0xd4, 0x02, 0x00, 0x04, 0x00])
const PCAPNG_HEAD = Buffer.from([0x0a, 0x0d, 0x0d, 0x0a, 0x1c, 0x00, 0x00, 0x00])
const ELF_CORE_HEAD = Buffer.from([0x7f, 0x45, 0x4c, 0x46, 0x02, 0x01, 0x01, 0x00])
const GARBAGE_HEAD = Buffer.from('GARBAGE: not a capture or dump', 'utf8')

export interface ImportFixture {
  name: string
  head: Buffer
  /** Reported as the file's size instead of the bytes' length, so a limit can be exceeded without allocating. */
  reportedSize?: number
}

export const PCAP_FILE: ImportFixture = { name: 'lateral_movement.pcap', head: PCAP_HEAD }
export const PCAPNG_LONG_NAME_FILE: ImportFixture = {
  name: `capture_from_the_finance_segment_${'quarterly_reconciliation_'.repeat(5)}final_v2.pcapng`,
  head: PCAPNG_HEAD,
}
export const MEMORY_IMAGE_FILE: ImportFixture = { name: 'win10_workstation_memory.raw', head: ELF_CORE_HEAD }
export const UNSUPPORTED_FILE: ImportFixture = { name: 'notes.txt', head: GARBAGE_HEAD }
export const OVERSIZED_CAPTURE_FILE: ImportFixture = { name: 'month_long_capture.pcap', head: PCAP_HEAD, reportedSize: 600 * MIB }
export const OVERSIZED_MEMORY_IMAGE_FILE: ImportFixture = {
  name: 'server_memory_dump.raw',
  head: ELF_CORE_HEAD,
  reportedSize: 6 * GIB,
}
