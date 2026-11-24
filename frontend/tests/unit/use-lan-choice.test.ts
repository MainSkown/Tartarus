import { effectScope, nextTick, ref, type EffectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LanPreset, Route } from '@/api'
import { failed, succeeded } from './annotation-fixtures'

const lanPresetsList = vi.fn()
vi.mock('@/api', () => ({ lanPresetsList: (...args: unknown[]) => lanPresetsList(...args) }))

const { useLanChoice } = await import('@/composables/use-lan-choice')

function preset(id: string): LanPreset {
  return { id, name: `Preset ${id}`, description: 'A fake network', hosts: [] }
}

let scope: EffectScope

function start(initialRoute: Route = 'inetsim') {
  const route = ref<Route>(initialRoute)
  const choice = scope.run(() => useLanChoice(route))!
  return { route, choice }
}

const settle = () => nextTick().then(() => nextTick())

beforeEach(() => {
  lanPresetsList.mockReset()
  scope = effectScope()
})

afterEach(() => {
  scope.stop()
})

describe('useLanChoice', () => {
  describe('switched off', () => {
    it('is off by default, asks the backend nothing and blocks nothing', async () => {
      const { choice } = start()
      await settle()

      expect(choice.enabled.value).toBe(false)
      expect(lanPresetsList).not.toHaveBeenCalled()
      expect(choice.blockReason.value).toBeUndefined()
      expect(choice.optionPayload.value).toEqual({})
    })

    it('sends no preset even when one was chosen before the switch went off', async () => {
      lanPresetsList.mockResolvedValue(succeeded([preset('office'), preset('home')]))
      const { choice } = start()
      choice.enabled.value = true
      await settle()
      choice.presetId.value = 'home'
      choice.enabled.value = false

      expect(choice.optionPayload.value).toEqual({})
      expect(choice.blockReason.value).toBeUndefined()
    })
  })

  describe('switched on', () => {
    it('asks for the presets and blocks submit while they load', async () => {
      lanPresetsList.mockReturnValue(new Promise(() => undefined))
      const { choice } = start()

      choice.enabled.value = true
      await settle()

      expect(lanPresetsList).toHaveBeenCalledTimes(1)
      expect(choice.presets.loading.value).toBe(true)
      expect(choice.blockReason.value).toBe('Reading the local network presets…')
    })

    it('asks the backend once however often the switch is flipped', async () => {
      lanPresetsList.mockResolvedValue(succeeded([preset('office'), preset('home')]))
      const { choice } = start()

      choice.enabled.value = true
      await settle()
      choice.enabled.value = false
      await settle()
      choice.enabled.value = true
      await settle()

      expect(lanPresetsList).toHaveBeenCalledTimes(1)
    })

    it('chooses nothing when there are several presets, and blocks until one is chosen', async () => {
      lanPresetsList.mockResolvedValue(succeeded([preset('office'), preset('home'), preset('domain')]))
      const { choice } = start()

      choice.enabled.value = true
      await settle()

      expect(choice.presetId.value).toBeNull()
      expect(choice.blockReason.value).toBe('Choose a local network preset')
      expect(choice.optionPayload.value).toEqual({})
    })

    it('sends the chosen preset and blocks nothing', async () => {
      lanPresetsList.mockResolvedValue(succeeded([preset('office'), preset('home')]))
      const { choice } = start()
      choice.enabled.value = true
      await settle()

      choice.presetId.value = 'home'

      expect(choice.blockReason.value).toBeUndefined()
      expect(choice.optionPayload.value).toEqual({ lan_preset: 'home' })
    })

    it('chooses the only preset there is', async () => {
      lanPresetsList.mockResolvedValue(succeeded([preset('office')]))
      const { choice } = start()

      choice.enabled.value = true
      await settle()

      expect(choice.presetId.value).toBe('office')
      expect(choice.blockReason.value).toBeUndefined()
      expect(choice.optionPayload.value).toEqual({ lan_preset: 'office' })
    })

    it('blocks submit when the backend knows no preset', async () => {
      lanPresetsList.mockResolvedValue(succeeded([]))
      const { choice } = start()

      choice.enabled.value = true
      await settle()

      expect(choice.blockReason.value).toBe('No local network preset is available')
    })

    it('blocks submit when the presets cannot be loaded, and unblocks after a retry', async () => {
      lanPresetsList.mockResolvedValueOnce(failed('down', 502)).mockResolvedValueOnce(succeeded([preset('office')]))
      const { choice } = start()
      choice.enabled.value = true
      await settle()
      expect(choice.blockReason.value).toBe('The local network presets could not be loaded')

      await choice.presets.retry()

      expect(choice.blockReason.value).toBeUndefined()
      expect(choice.optionPayload.value).toEqual({ lan_preset: 'office' })
    })
  })

  describe('the route', () => {
    it('is refused with the internet route', () => {
      expect(start('internet').choice.routeRefused.value).toBe(true)
      expect(start('none').choice.routeRefused.value).toBe(false)
    })

    it('switches itself off when the route changes to internet, keeping what was chosen', async () => {
      lanPresetsList.mockResolvedValue(succeeded([preset('office'), preset('home')]))
      const { route, choice } = start()
      choice.enabled.value = true
      await settle()
      choice.presetId.value = 'home'

      route.value = 'internet'
      await settle()

      expect(choice.enabled.value).toBe(false)
      expect(choice.optionPayload.value).toEqual({})
      expect(choice.blockReason.value).toBeUndefined()
    })

    it('stays off when the route goes back to a built one', async () => {
      const { route, choice } = start('internet')
      route.value = 'drop'
      await settle()

      expect(choice.enabled.value).toBe(false)
    })
  })
})
