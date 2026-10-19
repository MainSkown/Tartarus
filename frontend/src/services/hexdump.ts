export interface HexRow {
  offset: string
  bytes: string[]
  text: string
}

const BYTES_PER_ROW = 16
const OFFSET_DIGITS = 4
const FIRST_PRINTABLE = 0x20
const LAST_PRINTABLE = 0x7e
const NOT_PRINTABLE = '.'

function printable(byte: string): string {
  const code = Number.parseInt(byte, 16)
  return code >= FIRST_PRINTABLE && code <= LAST_PRINTABLE ? String.fromCharCode(code) : NOT_PRINTABLE
}

/** Volatility's `Hexdump` is bytes in hex separated by spaces, with no offsets or characters; this lays it out as a classic hex dump. */
export function hexRows(hexdump: string): HexRow[] {
  const bytes = hexdump.split(/\s+/).filter((byte) => byte !== '')
  const rows: HexRow[] = []
  for (let start = 0; start < bytes.length; start += BYTES_PER_ROW) {
    const rowBytes = bytes.slice(start, start + BYTES_PER_ROW)
    rows.push({ offset: start.toString(16).padStart(OFFSET_DIGITS, '0'), bytes: rowBytes, text: rowBytes.map(printable).join('') })
  }
  return rows
}

/** The lines of Volatility's `Disasm`, which it prints wrapped in a stray pair of quotes, with tabs as two spaces. */
export function disasmLines(disasm: string): string[] {
  return disasm
    .replace(/^"|"$/g, '')
    .split('\n')
    .map((line) => line.trim().replaceAll('\t', '  '))
    .filter((line) => line !== '')
}
