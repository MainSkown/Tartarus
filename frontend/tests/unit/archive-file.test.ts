import { describe, expect, it, vi } from 'vitest'
import type { ArchiveMemberRead } from '@/api'
import { hasEncryptedMember, isSelectableMember, isZipFile } from '@/services/archive-file'

const ZIP_MAGIC = [0x50, 0x4b, 0x03, 0x04]

function member(overrides: Partial<ArchiveMemberRead> = {}): ArchiveMemberRead {
  return { name: 'a.exe', size: 10, encrypted: false, unsafe: false, unsupported: false, ...overrides }
}

describe('isZipFile', () => {
  it.each(['a.zip', 'A.ZIP', 'sample.Zip', 'weird name.tar.zip'])('takes %s for a zip by its name', async (name) => {
    expect(await isZipFile(new File(['not a zip at all'], name))).toBe(true)
  })

  it('does not read the file when the name already says zip', async () => {
    const file = new File(['x'], 'a.zip')
    const slice = vi.spyOn(file, 'slice')
    await isZipFile(file)
    expect(slice).not.toHaveBeenCalled()
  })

  it('takes a file for a zip when it starts with PK, whatever its name', async () => {
    expect(await isZipFile(new File([new Uint8Array(ZIP_MAGIC)], 'invoice.bin'))).toBe(true)
  })

  it('reads only the first two bytes', async () => {
    const file = new File([new Uint8Array([...ZIP_MAGIC, 1, 2, 3])], 'invoice.bin')
    const slice = vi.spyOn(file, 'slice')
    await isZipFile(file)
    expect(slice).toHaveBeenCalledWith(0, 2)
  })

  it.each([
    ['a PE file', 'MZ-binary', 'invoice.exe'],
    ['an empty file', '', 'empty.bin'],
    ['a single P', 'P', 'p.bin'],
    ['a name that only mentions zip', 'MZ', 'zip.exe'],
    ['a name ending in zip without the dot', 'MZ', 'unzip'],
  ])('does not take %s for a zip', async (_label, content, name) => {
    expect(await isZipFile(new File([content], name))).toBe(false)
  })
})

describe('isSelectableMember', () => {
  it('accepts a plain member', () => {
    expect(isSelectableMember(member())).toBe(true)
  })

  it.each([{ unsafe: true }, { unsupported: true }])('refuses %j', (flag) => {
    expect(isSelectableMember(member(flag))).toBe(false)
  })
})

describe('hasEncryptedMember', () => {
  it('is true when any member is encrypted', () => {
    expect(hasEncryptedMember([member(), member({ encrypted: true })])).toBe(true)
  })

  it('is false when none is, and for an empty list', () => {
    expect(hasEncryptedMember([member()])).toBe(false)
    expect(hasEncryptedMember([])).toBe(false)
  })
})
