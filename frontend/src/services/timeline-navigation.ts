import type { Span } from '@/services/timeline-scale'

/** A change of the visible range the canvas asks for; the Timeline tab hands each to the store. */
export type Navigation =
  | { kind: 'zoom'; time: number; factor: number }
  | { kind: 'pan-pixels'; dx: number; width: number }
  | { kind: 'pan-fraction'; fraction: number }
  | { kind: 'jump'; edge: 'start' | 'end' }
  | { kind: 'view'; span: Span }
  | { kind: 'fit' }

export interface NavigationTarget {
  zoomAt: (time: number, factor: number) => void
  panByPixels: (dx: number, width: number) => void
  panByFraction: (fraction: number) => void
  jumpTo: (edge: 'start' | 'end') => void
  setView: (span: Span) => void
  fit: () => void
}

export function applyNavigation(target: NavigationTarget, navigation: Navigation): void {
  switch (navigation.kind) {
    case 'zoom':
      return target.zoomAt(navigation.time, navigation.factor)
    case 'pan-pixels':
      return target.panByPixels(navigation.dx, navigation.width)
    case 'pan-fraction':
      return target.panByFraction(navigation.fraction)
    case 'jump':
      return target.jumpTo(navigation.edge)
    case 'view':
      return target.setView(navigation.span)
    case 'fit':
      return target.fit()
  }
}
