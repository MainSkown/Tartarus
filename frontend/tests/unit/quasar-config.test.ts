import type { GenerateSWOptions } from 'workbox-build'
import { afterEach, describe, expect, it, vi } from 'vitest'

async function loadConfig() {
  vi.resetModules()
  const { default: configure } = await import('../../quasar.config')
  return configure({} as Parameters<typeof configure>[0])
}

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('quasar.config', () => {
  it('is dark only, with the notify, dialog, loading and storage plugins', async () => {
    const { framework } = await loadConfig()
    expect(framework?.config).toMatchObject({ dark: true })
    expect(framework?.plugins).toEqual(['Notify', 'Dialog', 'Loading', 'LocalStorage'])
  })

  it('proxies /api and /ws (websocket-enabled) to the backend by default', async () => {
    const { devServer } = await loadConfig()
    expect(devServer?.host).toBe('0.0.0.0')
    expect(devServer?.port).toBe(5173)
    expect(devServer?.proxy).toMatchObject({
      '/api': { target: 'http://backend:8000' },
      '/ws': { target: 'http://backend:8000', ws: true },
    })
  })

  it('answers only the loopback host names, so a rebound DNS name cannot reach the dev server', async () => {
    const { devServer } = await loadConfig()
    expect(devServer?.allowedHosts).toEqual(['localhost'])
  })

  it('takes the dev server port from DEV_SERVER_PORT, so the screenshot harness can run its own instance', async () => {
    vi.stubEnv('DEV_SERVER_PORT', '5190')
    const { devServer } = await loadConfig()
    expect(devServer?.port).toBe(5190)
  })

  it('takes the proxy target from API_PROXY_TARGET', async () => {
    vi.stubEnv('API_PROXY_TARGET', 'http://127.0.0.1:9000')
    const { devServer } = await loadConfig()
    expect(devServer?.proxy).toMatchObject({
      '/api': { target: 'http://127.0.0.1:9000' },
      '/ws': { target: 'http://127.0.0.1:9000' },
    })
  })

  it('registers the notify and api boot files and the theme stylesheet', async () => {
    const { boot, css } = await loadConfig()
    expect(boot).toContain('notify')
    expect(boot).toContain('api')
    expect(css).toEqual(['app.css'])
  })

  it('precaches only the app shell: no runtime caching, no navigation fallback for /api or /ws', async () => {
    const { pwa } = await loadConfig()
    expect(pwa?.workboxMode).toBe('GenerateSW')
    const options: Partial<GenerateSWOptions> = {}
    await pwa?.extendPWAGenerateSWOptions?.(options as GenerateSWOptions)
    expect(options.runtimeCaching).toEqual([])
    const denied = options.navigateFallbackDenylist ?? []
    expect(denied.some((pattern) => pattern.test('/api/system/health'))).toBe(true)
    expect(denied.some((pattern) => pattern.test('/ws/system'))).toBe(true)
    expect(denied.some((pattern) => pattern.test('/analyses/42'))).toBe(false)
  })
})
