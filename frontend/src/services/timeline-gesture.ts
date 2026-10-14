import { brushSpan, moveHandle, type RangeHandle } from '@/services/timeline-brush'
import type { Hit } from '@/services/timeline-hit-test'
import type { Span } from '@/services/timeline-scale'

export const DRAG_THRESHOLD_PX = 3

export interface GestureContext {
  view: Span
  full: Span
  plotWidth: number
  /** Where the plot starts on the canvas; the pointer comes in canvas pixels and the brush works in plot pixels. */
  gutter: number
  /** The time-range chip as a span, which the handles move. */
  chip: Span | null
}

export type GestureEffect =
  | { type: 'click'; hit: Hit }
  | { type: 'pan'; dx: number }
  | { type: 'brush'; span: Span | null }
  | { type: 'brush-end'; span: Span | null }
  | { type: 'handle'; handle: RangeHandle; span: Span }
  | { type: 'handle-end'; handle: RangeHandle; span: Span }
  | { type: 'cancel' }

type State =
  | { mode: 'idle' }
  | { mode: 'press'; hit: Hit; x: number; y: number }
  | { mode: 'pan'; lastX: number }
  | { mode: 'brush'; anchorX: number }
  | { mode: 'handle'; handle: RangeHandle; span: Span; moved: boolean }

export type GestureMode = State['mode']

/**
 * What a pointer press, drag and release mean on the timeline. A press on the plot is a click until
 * it moves `DRAG_THRESHOLD_PX`, then a pan; on the axis it is a brush; on a handle of the time-range
 * chip it moves that end. Each call returns the effect to apply, if any.
 */
export function createGesture(context: () => GestureContext) {
  let state: State = { mode: 'idle' }

  function plotX(x: number): number {
    return x - context().gutter
  }

  function brushed(anchorX: number, x: number): Span | null {
    const { view, plotWidth, full } = context()
    return brushSpan(anchorX, plotX(x), view, plotWidth, full)
  }

  function dragged(handle: RangeHandle, span: Span, x: number): Span {
    const { view, plotWidth } = context()
    return moveHandle(span, handle, plotX(x), view, plotWidth)
  }

  function down(hit: Hit | null, x: number, y: number): void {
    state = { mode: 'idle' }
    if (hit === null || hit.kind === 'gutter') return
    if (hit.kind === 'axis') state = { mode: 'brush', anchorX: plotX(x) }
    else if (hit.kind === 'handle') {
      const { chip } = context()
      if (chip) state = { mode: 'handle', handle: hit.handle, span: chip, moved: false }
    } else state = { mode: 'press', hit, x, y }
  }

  function move(x: number, y: number): GestureEffect | undefined {
    switch (state.mode) {
      case 'press': {
        if (Math.max(Math.abs(x - state.x), Math.abs(y - state.y)) < DRAG_THRESHOLD_PX) return undefined
        const dx = x - state.x
        state = { mode: 'pan', lastX: x }
        return { type: 'pan', dx }
      }
      case 'pan': {
        const dx = x - state.lastX
        state = { mode: 'pan', lastX: x }
        return { type: 'pan', dx }
      }
      case 'brush':
        return { type: 'brush', span: brushed(state.anchorX, x) }
      case 'handle':
        state = { ...state, moved: true }
        return { type: 'handle', handle: state.handle, span: dragged(state.handle, state.span, x) }
      default:
        return undefined
    }
  }

  function up(x: number): GestureEffect | undefined {
    const finished = state
    state = { mode: 'idle' }
    switch (finished.mode) {
      case 'press':
        return { type: 'click', hit: finished.hit }
      case 'brush':
        return { type: 'brush-end', span: brushed(finished.anchorX, x) }
      case 'handle':
        return finished.moved ? { type: 'handle-end', handle: finished.handle, span: dragged(finished.handle, finished.span, x) } : undefined
      default:
        return undefined
    }
  }

  function cancel(): GestureEffect | undefined {
    const cancelled = state.mode === 'pan' || state.mode === 'brush' || state.mode === 'handle'
    state = { mode: 'idle' }
    return cancelled ? { type: 'cancel' } : undefined
  }

  return {
    get mode(): GestureMode {
      return state.mode
    },
    down,
    move,
    up,
    cancel,
  }
}
