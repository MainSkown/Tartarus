import { describe, expect, it } from 'vitest'
import { editionCount, mediaDetails, variantLabel } from '@/services/guest-media-view'
import { BROKEN_MEDIA, mediaEntry } from './guest-wizard-fixtures'

describe('variantLabel', () => {
  const home = { name: 'Windows 11 Home', default_language: 'pl-PL' }

  it('writes the edition name and its language', () => {
    expect(variantLabel(home, 'en-US')).toBe('Windows 11 Home · pl-PL')
  })

  it("falls back to the medium's language when the edition names none", () => {
    expect(variantLabel({ name: 'Windows 11 Home' }, 'en-US')).toBe('Windows 11 Home · en-US')
  })

  it('is just the name when no language is known', () => {
    expect(variantLabel({ name: 'Windows 11 Home' }, null)).toBe('Windows 11 Home')
  })
})

describe('editionCount', () => {
  it('counts the editions and says so in the singular', () => {
    expect(editionCount(mediaEntry())).toBe('2 editions')
    expect(editionCount(mediaEntry({ variants: [mediaEntry().variants![0]!] }))).toBe('1 edition')
  })

  it('is nothing for a medium that lists none', () => {
    expect(editionCount(mediaEntry({ variants: [] }))).toBeUndefined()
  })
})

describe('mediaDetails', () => {
  it('lists the version, build, language, architecture and editions the image carried', () => {
    expect(mediaDetails(mediaEntry())).toEqual(['10.0.26200', 'pl-PL', 'x64', '2 editions'])
  })

  it('adds the build number when the version does not already hold it', () => {
    expect(mediaDetails(mediaEntry({ version: '25H2', build: 26200 }))).toContain('build 26200')
  })

  it('has nothing to list for an image nothing could read', () => {
    expect(mediaDetails(BROKEN_MEDIA)).toEqual([])
  })
})
