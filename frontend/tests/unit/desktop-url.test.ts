import { describe, expect, it } from 'vitest'
import { analysisDesktopPath, guestDesktopPath } from '@/services/desktop-url'

describe('desktop paths', () => {
  it('is the analysis socket for an analysis', () => {
    expect(analysisDesktopPath(45)).toBe('/ws/analyses/45/desktop')
  })

  it('is the guest socket for the guest of a build', () => {
    expect(guestDesktopPath('lab4')).toBe('/ws/guests/lab4/desktop')
  })

  it('encodes a guest name so that it can never add path segments', () => {
    expect(guestDesktopPath('a/b?c')).toBe('/ws/guests/a%2Fb%3Fc/desktop')
  })
})
