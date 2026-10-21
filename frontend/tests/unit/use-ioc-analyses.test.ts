import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { effectScope, ref } from 'vue'
import type { IocType } from '@/api'

const iocsAnalyses = vi.hoisted(() => vi.fn())
vi.mock('@/api', () => ({ iocsAnalyses }))

const { useIocAnalyses } = await import('@/composables/use-ioc-analyses')

function mountAnalyses(kind: IocType, value: string) {
  const kindRef = ref<IocType>(kind)
  const valueRef = ref(value)
  const scope = effectScope()
  const state = scope.run(() => useIocAnalyses(() => kindRef.value, () => valueRef.value))!
  return { state, kindRef, valueRef }
}

const hits = [
  { analysis_id: 45, count: 12 },
  { analysis_id: 51, count: 1 },
]

beforeEach(() => {
  iocsAnalyses.mockReset()
  iocsAnalyses.mockResolvedValue({ data: hits, response: { status: 200 } })
})

describe('useIocAnalyses', () => {
  it('asks the analyses of the kind and value, quietly on a 422', async () => {
    mountAnalyses('domain', 'pivot-request.test')
    await flushPromises()
    expect(iocsAnalyses).toHaveBeenCalledTimes(1)
    expect(iocsAnalyses).toHaveBeenCalledWith({
      path: { kind: 'domain', value: 'pivot-request.test' },
      meta: { quietStatuses: [422] },
    })
  })

  it('is loading until the answer arrives, then holds the analyses', async () => {
    const { state } = mountAnalyses('ip', 'loading.test')
    expect(state.value).toEqual({ status: 'loading' })
    await flushPromises()
    expect(state.value).toEqual({ status: 'seen', analyses: hits })
  })

  it('is not pivotable when the server refuses the kind with a 422', async () => {
    iocsAnalyses.mockResolvedValue({ error: { error: { code: 'x', message: 'mutex' } }, response: { status: 422 } })
    const { state } = mountAnalyses('mutex', 'Global\\refused.test')
    await flushPromises()
    expect(state.value).toEqual({ status: 'notPivotable' })
  })

  it('is failed on any other error, and asks again the next time', async () => {
    iocsAnalyses.mockResolvedValueOnce({ error: { error: { code: 'x', message: 'boom' } }, response: { status: 500 } })
    const first = mountAnalyses('url', 'https://failed.test/a')
    await flushPromises()
    expect(first.state.value).toEqual({ status: 'failed' })

    const second = mountAnalyses('url', 'https://failed.test/a')
    await flushPromises()
    expect(second.state.value).toEqual({ status: 'seen', analyses: hits })
    expect(iocsAnalyses).toHaveBeenCalledTimes(2)
  })

  it('is failed when the request itself throws', async () => {
    iocsAnalyses.mockRejectedValueOnce(new TypeError('network down'))
    const { state } = mountAnalyses('file', 'C:\\throws.test')
    await flushPromises()
    expect(state.value).toEqual({ status: 'failed' })
  })

  it('does not ask again for a kind and value it already has', async () => {
    mountAnalyses('hash', 'cached-hash.test')
    await flushPromises()
    const again = mountAnalyses('hash', 'cached-hash.test')
    await flushPromises()
    expect(again.state.value).toEqual({ status: 'seen', analyses: hits })
    expect(iocsAnalyses).toHaveBeenCalledTimes(1)
  })

  it('shares one request between two mounts that start together', async () => {
    mountAnalyses('registry', 'HKCU\\Shared')
    mountAnalyses('registry', 'HKCU\\Shared')
    await flushPromises()
    expect(iocsAnalyses).toHaveBeenCalledTimes(1)
  })

  it('keeps a 422 answer, so a refused value is not asked again either', async () => {
    iocsAnalyses.mockResolvedValue({ error: { error: { code: 'x', message: 'mutex' } }, response: { status: 422 } })
    mountAnalyses('mutex', 'Global\\refused-again.test')
    await flushPromises()
    const again = mountAnalyses('mutex', 'Global\\refused-again.test')
    await flushPromises()
    expect(again.state.value).toEqual({ status: 'notPivotable' })
    expect(iocsAnalyses).toHaveBeenCalledTimes(1)
  })

  it('asks for the new value when the value changes', async () => {
    const { state, valueRef } = mountAnalyses('ip', '10.0.0.1')
    await flushPromises()
    valueRef.value = '10.0.0.2'
    await flushPromises()
    expect(iocsAnalyses).toHaveBeenLastCalledWith({ path: { kind: 'ip', value: '10.0.0.2' }, meta: { quietStatuses: [422] } })
    expect(state.value).toEqual({ status: 'seen', analyses: hits })
  })
})
