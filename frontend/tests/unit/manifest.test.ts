import { existsSync, readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

interface ManifestIcon {
  src: string
  sizes: string
  purpose?: string
}

const manifest = JSON.parse(readFileSync('src-pwa/manifest.json', 'utf8')) as {
  [key: string]: unknown
  icons: ManifestIcon[]
}

describe('PWA manifest', () => {
  it('describes a standalone black-on-black Tartarus app', () => {
    expect(manifest).toMatchObject({
      name: 'Tartarus',
      short_name: 'Tartarus',
      display: 'standalone',
      background_color: '#000000',
      theme_color: '#000000',
    })
  })

  it('ships 192, 512 and maskable icons that exist in public/', () => {
    const sizesAndPurposes = manifest.icons.map(({ sizes, purpose }) => `${sizes}${purpose ? ` ${purpose}` : ''}`)
    expect(sizesAndPurposes).toEqual(['192x192', '512x512', '512x512 maskable'])
    for (const { src } of manifest.icons) {
      expect(existsSync(`public/${src}`), src).toBe(true)
    }
  })
})
