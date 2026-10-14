import { afterEach, describe, expect, it, vi } from 'vitest'
import { readStored, writeStored } from '@/services/viewer-storage'

afterEach(() => {
  window.localStorage.clear()
})

describe('readStored', () => {
  it('returns the fallback when nothing is stored', () => {
    expect(readStored('k', ['a'])).toEqual(['a'])
  })

  it('returns what writeStored put there, whatever its shape', () => {
    writeStored('k', { open: true, ids: [1, 2] })
    expect(readStored('k', null)).toEqual({ open: true, ids: [1, 2] })
  })

  it('returns the fallback for a value that is not valid JSON', () => {
    window.localStorage.setItem('k', '{not json')
    expect(readStored('k', 'fallback')).toBe('fallback')
  })

  it('returns the fallback when the browser refuses storage', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    expect(readStored('k', 7)).toBe(7)
  })

  it('returns the fallback when the stored value fails the check', () => {
    writeStored('k', 'not a list')
    expect(readStored('k', [] as string[], Array.isArray)).toEqual([])
  })
})

describe('writeStored', () => {
  it('does not throw when the browser refuses storage', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })
    expect(() => writeStored('k', 1)).not.toThrow()
  })
})
