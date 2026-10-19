import { describe, expect, it } from 'vitest'
import { splitPath } from '@/services/file-path'

describe('splitPath', () => {
  it('keeps the trailing separator with the directory so the two halves join back to the path', () => {
    expect(splitPath('C:\\Users\\Alice\\AppData\\Local\\Temp\\321\\eicar.com')).toEqual({
      directory: 'C:\\Users\\Alice\\AppData\\Local\\Temp\\321\\',
      name: 'eicar.com',
    })
  })

  it('splits a forward-slash path too', () => {
    expect(splitPath('/tmp/a/b.bin')).toEqual({ directory: '/tmp/a/', name: 'b.bin' })
  })

  it('has no directory for a bare file name', () => {
    expect(splitPath('eicar.com')).toEqual({ directory: '', name: 'eicar.com' })
  })
})
