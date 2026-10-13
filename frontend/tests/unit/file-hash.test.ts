import { describe, expect, it } from 'vitest'
import { sha256Hex } from '@/services/file-hash'

describe('sha256Hex', () => {
  it('hashes the empty file to the well-known empty digest', async () => {
    await expect(sha256Hex(new File([], 'empty.bin'))).resolves.toBe(
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    )
  })

  it('hashes the file contents as lowercase hex', async () => {
    await expect(sha256Hex(new File(['abc'], 'abc.txt'))).resolves.toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    )
  })
})
