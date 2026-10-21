const MIB = 1024 ** 2
const GIB = 1024 ** 3

/** Mirrors `Settings.import_pcap_max_bytes` and `import_memory_image_max_bytes` in the backend. */
export const IMPORT_LIMIT_BYTES = {
  capture: 512 * MIB,
  memory_image: 5 * GIB,
} as const

export type ImportSizeClass = keyof typeof IMPORT_LIMIT_BYTES
