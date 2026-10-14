/** Rows from the end of what is loaded at which the next page is asked for, so it lands before the user gets there. */
export const LOAD_MORE_MARGIN = 30

export interface PagingState {
  lastRendered: number
  loaded: number
  hasMore: boolean
  busy: boolean
}

export function shouldLoadMore({ lastRendered, loaded, hasMore, busy }: PagingState): boolean {
  return hasMore && !busy && loaded > 0 && lastRendered >= loaded - LOAD_MORE_MARGIN
}

export interface RevealRequest {
  index: number
  scrollTop: number
  viewportHeight: number
  rowHeight: number
}

/** The scroll position that shows row `index` in full, moving as little as possible. */
export function scrollTopToReveal({ index, scrollTop, viewportHeight, rowHeight }: RevealRequest): number {
  const rowTop = index * rowHeight
  const rowBottom = rowTop + rowHeight
  if (rowTop < scrollTop) return rowTop
  if (rowBottom > scrollTop + viewportHeight) return rowBottom - viewportHeight
  return scrollTop
}
