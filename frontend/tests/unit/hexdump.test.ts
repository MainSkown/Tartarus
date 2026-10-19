import { describe, expect, it } from 'vitest'
import { disasmLines, hexRows } from '@/services/hexdump'

describe('hexRows', () => {
  it('breaks the bytes into rows of 16 with the offset in hex and the printable characters', () => {
    const bytes = Array.from({ length: 20 }, (_, index) => (0x41 + index).toString(16)).join(' ')
    expect(hexRows(bytes)).toEqual([
      { offset: '0000', bytes: Array.from({ length: 16 }, (_, index) => (0x41 + index).toString(16)), text: 'ABCDEFGHIJKLMNOP' },
      { offset: '0010', bytes: ['51', '52', '53', '54'], text: 'QRST' },
    ])
  })

  it('shows a dot for a byte that is not printable', () => {
    expect(hexRows('4d 5a 00 90 ff 7f')[0]?.text).toBe('MZ....')
  })

  it('accepts bytes separated by any whitespace, and upper case', () => {
    expect(hexRows('4D\n5A\t90')[0]?.bytes).toEqual(['4D', '5A', '90'])
  })

  it('is empty for an empty dump', () => {
    expect(hexRows('')).toEqual([])
    expect(hexRows('   ')).toEqual([])
  })
})

describe('disasmLines', () => {
  it('splits the listing into lines and drops the stray quotes Volatility prints around it', () => {
    expect(disasmLines('"\n0x198fe590000:\tpush\trbp\n0x198fe590001:\tret\t"')).toEqual(['0x198fe590000:  push  rbp', '0x198fe590001:  ret'])
  })

  it('is empty for an empty listing', () => {
    expect(disasmLines('""')).toEqual([])
    expect(disasmLines('')).toEqual([])
  })
})
