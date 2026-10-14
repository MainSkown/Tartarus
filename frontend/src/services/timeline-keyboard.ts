export type KeyCommand =
  | { type: 'pan'; fraction: number }
  | { type: 'zoom'; factor: number }
  | { type: 'fit' }
  | { type: 'jump'; edge: 'start' | 'end' }
  | { type: 'escape' }

interface KeyPress {
  key: string
  shiftKey?: boolean
  ctrlKey?: boolean
  metaKey?: boolean
  altKey?: boolean
}

const PAN_FRACTION = 0.25
const ZOOM_STEP = 2

/** What a key does on the focused timeline; null for a key it leaves alone, including every chord, which belongs to the browser. */
export function keyCommand({ key, shiftKey = false, ctrlKey = false, metaKey = false, altKey = false }: KeyPress): KeyCommand | null {
  if (ctrlKey || metaKey || altKey) return null
  const pan = shiftKey ? 1 : PAN_FRACTION
  switch (key) {
    case 'ArrowLeft':
      return { type: 'pan', fraction: -pan }
    case 'ArrowRight':
      return { type: 'pan', fraction: pan }
    case '+':
    case '=':
      return { type: 'zoom', factor: 1 / ZOOM_STEP }
    case '-':
    case '_':
      return { type: 'zoom', factor: ZOOM_STEP }
    case '0':
      return { type: 'fit' }
    case 'Home':
      return { type: 'jump', edge: 'start' }
    case 'End':
      return { type: 'jump', edge: 'end' }
    case 'Escape':
      return { type: 'escape' }
    default:
      return null
  }
}
