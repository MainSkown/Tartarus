import { nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FACET_PANEL_STORAGE_KEY, useFacetPanel } from '@/composables/use-facet-panel'

afterEach(() => {
  window.localStorage.clear()
  vi.restoreAllMocks()
})

describe('useFacetPanel', () => {
  it('starts open', () => {
    expect(useFacetPanel().open.value).toBe(true)
  })

  it('toggles', () => {
    const panel = useFacetPanel()
    panel.toggle()
    expect(panel.open.value).toBe(false)
    panel.toggle()
    expect(panel.open.value).toBe(true)
  })

  it('remembers a collapsed panel', async () => {
    useFacetPanel().toggle()
    await nextTick()
    expect(window.localStorage.getItem(FACET_PANEL_STORAGE_KEY)).toBe('false')
    expect(useFacetPanel().open.value).toBe(false)
  })

  it('stays open when the stored value is not a flag', () => {
    window.localStorage.setItem(FACET_PANEL_STORAGE_KEY, '"x"')
    expect(useFacetPanel().open.value).toBe(true)
  })

  it('works when storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    const panel = useFacetPanel()
    expect(panel.open.value).toBe(true)
    expect(() => panel.toggle()).not.toThrow()
    expect(panel.open.value).toBe(false)
  })
})
