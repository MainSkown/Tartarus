import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useQueryStateStore } from '@/stores/query-state'

const CMD: { field: string; value: string; negate: boolean } = { field: 'process.name', value: 'cmd.exe', negate: false }

let store: ReturnType<typeof useQueryStateStore>

beforeEach(() => {
  setActivePinia(createPinia())
  store = useQueryStateStore()
})

describe('the empty state', () => {
  it('starts empty, and its search filter has nothing in it', () => {
    expect(store.isEmpty).toBe(true)
    expect(store.searchFilter).toEqual({})
  })
})

describe('text', () => {
  it('sets the applied text', () => {
    store.setText('lane:network')
    expect(store.text).toBe('lane:network')
    expect(store.isEmpty).toBe(false)
    expect(store.searchFilter).toEqual({ query: 'lane:network' })
  })

  it('treats a blank text as no query', () => {
    store.setText('   ')
    expect(store.searchFilter).toEqual({})
    expect(store.isEmpty).toBe(true)
  })
})

describe('chips', () => {
  it('adds a chip', () => {
    store.addChip(CMD)
    expect(store.chips).toEqual([CMD])
    expect(store.searchFilter).toEqual({ filters: [CMD] })
  })

  it('does not duplicate a chip on the same field and value, it replaces its direction', () => {
    store.addChip(CMD)
    store.addChip({ ...CMD, negate: true })
    expect(store.chips).toEqual([{ ...CMD, negate: true }])
  })

  it('keeps the position of a chip whose direction was replaced', () => {
    store.addChip(CMD)
    store.addChip({ field: 'lane', value: 'file', negate: false })
    store.addChip({ ...CMD, negate: true })
    expect(store.chips.map((chip) => chip.field)).toEqual(['process.name', 'lane'])
  })

  it('keeps two chips on the same field with different values', () => {
    store.addChip(CMD)
    store.addChip({ ...CMD, value: 'powershell.exe' })
    expect(store.chips).toHaveLength(2)
  })

  it('toggles a chip between is and is not', () => {
    store.addChip(CMD)
    store.toggleChip(0)
    expect(store.chips[0]!.negate).toBe(true)
    store.toggleChip(0)
    expect(store.chips[0]!.negate).toBe(false)
  })

  it('ignores toggling and removing a chip that is not there', () => {
    store.addChip(CMD)
    store.toggleChip(5)
    store.removeChip(-1)
    expect(store.chips).toEqual([CMD])
  })

  it('removes a chip by position', () => {
    store.addChip(CMD)
    store.addChip({ field: 'lane', value: 'file', negate: false })
    store.removeChip(0)
    expect(store.chips.map((chip) => chip.field)).toEqual(['lane'])
  })
})

describe('pids', () => {
  it('sets the pids', () => {
    store.setPids([4120, 9708])
    expect(store.searchFilter).toEqual({ pids: [4120, 9708] })
  })

  it('leaves an empty pid list out, because the API reads it as "match nothing"', () => {
    store.setPids([4120])
    store.setPids([])
    expect(store.searchFilter).toEqual({})
  })

  it('toggles a pid in and out', () => {
    store.togglePid(4120)
    store.togglePid(9708)
    expect(store.pids).toEqual([4120, 9708])
    store.togglePid(4120)
    expect(store.pids).toEqual([9708])
  })
})

describe('time range', () => {
  it('sets a range and sends only the ends it has', () => {
    store.setTimeRange({ from: '2026-10-13T12:00:01Z', to: null })
    expect(store.searchFilter).toEqual({ time_range: { from: '2026-10-13T12:00:01Z' } })
    store.setTimeRange({ from: null, to: '2026-10-13T12:00:04Z' })
    expect(store.searchFilter).toEqual({ time_range: { to: '2026-10-13T12:00:04Z' } })
  })

  it('treats a range with no end as no range', () => {
    store.setTimeRange({ from: null, to: null })
    expect(store.timeRange).toBeNull()
    expect(store.isEmpty).toBe(true)
  })

  it('clears the range', () => {
    store.setTimeRange({ from: '2026-10-13T12:00:01Z', to: '2026-10-13T12:00:04Z' })
    store.clearTimeRange()
    expect(store.timeRange).toBeNull()
  })
})

describe('the open event', () => {
  it('opens and closes an event', () => {
    store.openEvent('e1')
    expect(store.eventId).toBe('e1')
    store.closeEvent()
    expect(store.eventId).toBeNull()
  })

  it('is part of the URL state but not of the search filter', () => {
    store.openEvent('e1')
    expect(store.urlState.eventId).toBe('e1')
    expect(store.searchFilter).toEqual({})
    expect(store.isEmpty).toBe(true)
  })

  it('closes when the analysis changes', () => {
    store.bindTo(1)
    store.openEvent('e1')
    store.bindTo(2)
    expect(store.eventId).toBeNull()
  })
})

describe('the search filter', () => {
  it('holds every part that is set, under the names of the API', () => {
    store.setText('lane:network')
    store.addChip({ ...CMD, negate: true })
    store.setPids([4120])
    store.setTimeRange({ from: '2026-10-13T12:00:01Z', to: '2026-10-13T12:00:04Z' })
    expect(store.searchFilter).toEqual({
      query: 'lane:network',
      filters: [{ ...CMD, negate: true }],
      time_range: { from: '2026-10-13T12:00:01Z', to: '2026-10-13T12:00:04Z' },
      pids: [4120],
    })
  })

  it('is a new object when something changes, so a watcher sees it', () => {
    const before = store.searchFilter
    store.setText('x')
    expect(store.searchFilter).not.toBe(before)
  })
})

describe('reset and restore', () => {
  it('resets every part', () => {
    store.setText('x')
    store.addChip(CMD)
    store.setPids([1])
    store.setTimeRange({ from: '2026-10-13T12:00:01Z', to: null })
    store.openEvent('e1')
    store.reset()
    expect(store.isEmpty).toBe(true)
    expect(store.urlState).toEqual({ text: '', chips: [], pids: [], timeRange: null, eventId: null })
  })

  it('restores a whole state at once', () => {
    const state = { text: 'a', chips: [CMD], pids: [3], timeRange: { from: null, to: '2026-10-13T12:00:04Z' }, eventId: 'e1' }
    store.restore(state)
    expect(store.urlState).toEqual(state)
  })

  it('does not share its arrays with the state it restored from', () => {
    const state = { text: '', chips: [CMD], pids: [3], timeRange: null, eventId: null }
    store.restore(state)
    store.togglePid(3)
    expect(state.pids).toEqual([3])
  })
})

describe('binding to an analysis', () => {
  it('resets when the analysis changes', () => {
    store.bindTo(1)
    store.setText('x')
    store.bindTo(2)
    expect(store.analysisId).toBe(2)
    expect(store.isEmpty).toBe(true)
  })

  it('keeps the state when bound to the same analysis again', () => {
    store.bindTo(1)
    store.setText('x')
    store.bindTo(1)
    expect(store.text).toBe('x')
  })
})
