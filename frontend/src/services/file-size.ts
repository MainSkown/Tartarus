const UNITS = ['B', 'KB', 'MB', 'GB']
const STEP = 1024

export function formatFileSize(bytes: number): string {
  let value = bytes
  let unit = 0
  while (value >= STEP && unit < UNITS.length - 1) {
    value /= STEP
    unit++
  }
  return `${Number(value.toFixed(1))} ${UNITS[unit]}`
}
