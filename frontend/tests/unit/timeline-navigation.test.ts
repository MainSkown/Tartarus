import { describe, expect, it, vi } from 'vitest'
import { applyNavigation, type Navigation } from '@/services/timeline-navigation'

function target() {
  return { zoomAt: vi.fn(), panByPixels: vi.fn(), panByFraction: vi.fn(), jumpTo: vi.fn(), setView: vi.fn(), fit: vi.fn() }
}

describe('applying a navigation to the timeline store', () => {
  it.each<[Navigation, keyof ReturnType<typeof target>, unknown[]]>([
    [{ kind: 'zoom', time: 5, factor: 0.5 }, 'zoomAt', [5, 0.5]],
    [{ kind: 'pan-pixels', dx: 12, width: 900 }, 'panByPixels', [12, 900]],
    [{ kind: 'pan-fraction', fraction: -0.25 }, 'panByFraction', [-0.25]],
    [{ kind: 'jump', edge: 'end' }, 'jumpTo', ['end']],
    [{ kind: 'view', span: { start: 1, end: 2 } }, 'setView', [{ start: 1, end: 2 }]],
    [{ kind: 'fit' }, 'fit', []],
  ])('%j', (navigation, method, args) => {
    const store = target()
    applyNavigation(store, navigation)
    expect(store[method]).toHaveBeenCalledWith(...args)
    for (const [name, mock] of Object.entries(store)) if (name !== method) expect(mock).not.toHaveBeenCalled()
  })
})
