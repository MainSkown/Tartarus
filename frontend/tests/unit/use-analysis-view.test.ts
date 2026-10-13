import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import { useAnalysisView } from '@/composables/use-analysis-view'

type Loaded = { items: number[] }
type Outcome = { data?: Loaded; error?: unknown }

function mountView(load: (id: number) => Promise<Outcome>, id = 7) {
  const analysisId = ref(id)
  const scope = effectScope()
  const view = scope.run(() => useAnalysisView(() => analysisId.value, load))!
  return { view, analysisId, stop: () => scope.stop() }
}

describe('useAnalysisView', () => {
  it('loads for the analysis id and exposes the data', async () => {
    const load = vi.fn().mockResolvedValue({ data: { items: [1, 2] } })
    const { view } = mountView(load)

    expect(view.loading.value).toBe(true)
    await flushPromises()

    expect(load).toHaveBeenCalledWith(7)
    expect(view.data.value).toEqual({ items: [1, 2] })
    expect(view.loading.value).toBe(false)
    expect(view.error.value).toBeUndefined()
  })

  it("exposes the backend's error message instead of data", async () => {
    const { view } = mountView(vi.fn().mockResolvedValue({ error: { error: { message: 'index is down' } } }))
    await flushPromises()

    expect(view.error.value).toBe('index is down')
    expect(view.data.value).toBeUndefined()
    expect(view.loading.value).toBe(false)
  })

  it('reloads on demand and clears an earlier error', async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce({ error: {} })
      .mockResolvedValueOnce({ data: { items: [3] } })
    const { view } = mountView(load)
    await flushPromises()
    expect(view.error.value).toBeDefined()

    await view.reload()

    expect(view.error.value).toBeUndefined()
    expect(view.data.value).toEqual({ items: [3] })
  })

  it('loads again, and drops the old data, when the analysis id changes', async () => {
    let finishSecond: (outcome: Outcome) => void = () => undefined
    const load = vi.fn((id: number): Promise<Outcome> =>
      id === 7 ? Promise.resolve({ data: { items: [7] } }) : new Promise((resolve) => (finishSecond = resolve)),
    )
    const { view, analysisId } = mountView(load)
    await flushPromises()
    expect(view.data.value).toEqual({ items: [7] })

    analysisId.value = 8
    await nextTick()
    expect(view.data.value).toBeUndefined()
    expect(view.loading.value).toBe(true)

    finishSecond({ data: { items: [8] } })
    await flushPromises()
    expect(load).toHaveBeenLastCalledWith(8)
    expect(view.data.value).toEqual({ items: [8] })
  })

  it('ignores a slow answer for an analysis that is no longer shown', async () => {
    const slow = new Promise<Outcome>((resolve) => setTimeout(() => resolve({ data: { items: [7] } }), 20))
    const load = vi.fn((id: number): Promise<Outcome> => (id === 7 ? slow : Promise.resolve({ data: { items: [id] } })))
    const { view, analysisId } = mountView(load)

    analysisId.value = 8
    await flushPromises()
    await slow

    expect(view.data.value).toEqual({ items: [8] })
  })
})
