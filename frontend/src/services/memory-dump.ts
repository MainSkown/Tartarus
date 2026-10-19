// The backend's refusal of a memory dump that would not fit on the CAPE volume; shown on the Submit dialog's field.
const MEMORY_DUMP_REFUSAL_PREFIX = 'A memory dump needs'
// The findings take about 0.3 GB on top of the dump, measured on S3.
const FINDINGS_GB = 0.3
const MB_PER_GB = 1024

/** The disk a memory dump of a guest with `ramMb` takes, in GB to one decimal, rounded up. */
export function memoryDumpDiskGb(ramMb: number): number {
  const dumpTenthsOfGb = Math.ceil((ramMb * 10) / MB_PER_GB)
  return (dumpTenthsOfGb + FINDINGS_GB * 10) / 10
}

export function isMemoryDumpRefusal(message: string): boolean {
  return message.startsWith(MEMORY_DUMP_REFUSAL_PREFIX)
}
