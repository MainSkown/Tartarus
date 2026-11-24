import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { LanPreset } from '@/api'
import { failed, succeeded } from './annotation-fixtures'

const lanPresetsList = vi.fn()
vi.mock('@/api', () => ({ lanPresetsList: (...args: unknown[]) => lanPresetsList(...args) }))

const { useLanPresets } = await import('@/composables/use-lan-presets')

function preset(id: string, overrides: Partial<LanPreset> = {}): LanPreset {
  return { id, name: `Preset ${id}`, description: 'A fake network', hosts: [], ...overrides }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

beforeEach(() => {
  lanPresetsList.mockReset()
})

describe('useLanPresets', () => {
  it('asks nothing until it is told to load', () => {
    const lan = useLanPresets()

    expect(lanPresetsList).not.toHaveBeenCalled()
    expect(lan.presets.value).toEqual([])
    expect(lan.loading.value).toBe(false)
    expect(lan.error.value).toBeUndefined()
  })

  it('is loading while the list is on its way, then holds the presets', async () => {
    const reply = deferred<ReturnType<typeof succeeded>>()
    lanPresetsList.mockReturnValue(reply.promise)
    const lan = useLanPresets()

    const loading = lan.load()
    expect(lan.loading.value).toBe(true)
    reply.resolve(succeeded([preset('office'), preset('home')]))
    await loading

    expect(lan.loading.value).toBe(false)
    expect(lan.presets.value.map((held) => held.id)).toEqual(['office', 'home'])
    expect(lan.error.value).toBeUndefined()
  })

  it('holds an empty list when the backend knows no preset', async () => {
    lanPresetsList.mockResolvedValue(succeeded([]))
    const lan = useLanPresets()

    await lan.load()

    expect(lan.presets.value).toEqual([])
    expect(lan.loading.value).toBe(false)
    expect(lan.error.value).toBeUndefined()
  })

  it('asks the backend once however often it is told to load', async () => {
    lanPresetsList.mockResolvedValue(succeeded([preset('office')]))
    const lan = useLanPresets()

    await Promise.all([lan.load(), lan.load()])
    await lan.load()

    expect(lanPresetsList).toHaveBeenCalledTimes(1)
  })

  it('keeps the backend error message and no presets when the list cannot be loaded', async () => {
    lanPresetsList.mockResolvedValue(failed('The guest control service is not reachable', 502))
    const lan = useLanPresets()

    await lan.load()

    expect(lan.error.value).toBe('The guest control service is not reachable')
    expect(lan.presets.value).toEqual([])
    expect(lan.loading.value).toBe(false)
  })

  it('asks without a toast for the failures the dialog shows inline', async () => {
    lanPresetsList.mockResolvedValue(succeeded([]))
    await useLanPresets().load()

    expect(lanPresetsList).toHaveBeenCalledWith({ meta: { quietStatuses: expect.arrayContaining([502]) } })
  })

  describe('after a failure', () => {
    it('loads again on retry and clears the error', async () => {
      lanPresetsList.mockResolvedValueOnce(failed('down', 502)).mockResolvedValueOnce(succeeded([preset('office')]))
      const lan = useLanPresets()
      await lan.load()

      const retrying = lan.retry()
      expect(lan.error.value).toBeUndefined()
      expect(lan.loading.value).toBe(true)
      await retrying

      expect(lan.presets.value.map((held) => held.id)).toEqual(['office'])
      expect(lan.error.value).toBeUndefined()
      expect(lanPresetsList).toHaveBeenCalledTimes(2)
    })

    it('loads again when told to load, since nothing was loaded', async () => {
      lanPresetsList.mockResolvedValueOnce(failed('down', 502)).mockResolvedValueOnce(succeeded([preset('office')]))
      const lan = useLanPresets()
      await lan.load()

      await lan.load()

      expect(lan.presets.value).toHaveLength(1)
    })

    it('can fail again', async () => {
      lanPresetsList.mockResolvedValue(failed('still down', 502))
      const lan = useLanPresets()
      await lan.load()

      await lan.retry()

      expect(lan.error.value).toBe('still down')
    })
  })
})
