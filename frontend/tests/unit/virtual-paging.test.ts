import { describe, expect, it } from 'vitest'
import { LOAD_MORE_MARGIN, scrollTopToReveal, shouldLoadMore } from '@/services/virtual-paging'

const BASE = { loaded: 100, hasMore: true, busy: false }

describe('shouldLoadMore', () => {
  it('loads when the last rendered row is within the margin of the end of what is loaded', () => {
    expect(shouldLoadMore({ ...BASE, lastRendered: 100 - LOAD_MORE_MARGIN })).toBe(true)
    expect(shouldLoadMore({ ...BASE, lastRendered: 99 })).toBe(true)
  })

  it('waits while the rows near the end are still far away', () => {
    expect(shouldLoadMore({ ...BASE, lastRendered: 100 - LOAD_MORE_MARGIN - 1 })).toBe(false)
    expect(shouldLoadMore({ ...BASE, lastRendered: 0 })).toBe(false)
  })

  it('does not load when there is no more, or a page is already on its way', () => {
    expect(shouldLoadMore({ ...BASE, lastRendered: 99, hasMore: false })).toBe(false)
    expect(shouldLoadMore({ ...BASE, lastRendered: 99, busy: true })).toBe(false)
  })

  it('does not load for an empty list, whatever the scroll position says', () => {
    expect(shouldLoadMore({ lastRendered: 0, loaded: 0, hasMore: true, busy: false })).toBe(false)
  })

  it('loads at once when the whole list is shorter than the margin', () => {
    expect(shouldLoadMore({ lastRendered: 5, loaded: 10, hasMore: true, busy: false })).toBe(true)
  })
})

describe('scrollTopToReveal', () => {
  const view = { rowHeight: 28, viewportHeight: 280 }

  it('leaves the scroll where it is when the row is fully in view', () => {
    expect(scrollTopToReveal({ ...view, index: 12, scrollTop: 280 })).toBe(280)
  })

  it('scrolls up just enough to show a row above the view', () => {
    expect(scrollTopToReveal({ ...view, index: 5, scrollTop: 280 })).toBe(140)
  })

  it('scrolls down just enough to show a row below the view', () => {
    expect(scrollTopToReveal({ ...view, index: 30, scrollTop: 280 })).toBe(30 * 28 + 28 - 280)
  })

  it('never scrolls above the top', () => {
    expect(scrollTopToReveal({ ...view, index: 0, scrollTop: 10 })).toBe(0)
  })
})
