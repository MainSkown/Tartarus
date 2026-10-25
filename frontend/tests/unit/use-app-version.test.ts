import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'

const systemVersion = vi.hoisted(() => vi.fn())
vi.mock('@/api', () => ({ systemVersion }))

const { useAppVersion } = await import('@/composables/use-app-version')

const INFO = { version: '1.0.0', commit: 'abc1234', license: 'GPL-3.0-only' }

function mountVersion() {
  const scope = effectScope()
  const version = scope.run(() => useAppVersion())!
  return { version, scope }
}

beforeEach(() => {
  systemVersion.mockReset()
  systemVersion.mockResolvedValue({ data: INFO, response: { status: 200 } })
})

describe('useAppVersion', () => {
  it('is loading until the version arrives, then holds it', async () => {
    const { version } = mountVersion()
    expect(version.state.value).toEqual({ status: 'loading' })

    await flushPromises()

    expect(version.state.value).toEqual({ status: 'loaded', info: INFO })
  })

  it('is failed when the server refuses the request', async () => {
    systemVersion.mockResolvedValue({ error: { error: { code: 'x', message: 'boom' } }, response: { status: 500 } })
    const { version } = mountVersion()
    await flushPromises()

    expect(version.state.value).toEqual({ status: 'failed' })
  })

  it('is failed when the request itself throws', async () => {
    systemVersion.mockRejectedValue(new TypeError('network down'))
    const { version } = mountVersion()
    await flushPromises()

    expect(version.state.value).toEqual({ status: 'failed' })
  })

  it('asks again on reload, and loads once the server answers', async () => {
    systemVersion.mockResolvedValueOnce({ error: { error: { code: 'x', message: 'boom' } }, response: { status: 500 } })
    const { version } = mountVersion()
    await flushPromises()

    await version.reload()

    expect(systemVersion).toHaveBeenCalledTimes(2)
    expect(version.state.value).toEqual({ status: 'loaded', info: INFO })
  })
})
