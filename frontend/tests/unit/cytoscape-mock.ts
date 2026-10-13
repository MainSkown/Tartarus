import { vi } from 'vitest'
import type { ElementDefinition } from 'cytoscape'

type Handler = (event: { target: { id: () => string; hasClass: (name: string) => boolean } }) => void

/** Just enough of cytoscape's Core for ProcessGraph; the real renderer needs a canvas jsdom lacks. */
export class FakeCytoscape {
  current: ElementDefinition[] = []
  readonly classes = new Map<string, Set<string>>()
  readonly handlers = new Map<string, Handler>()
  readonly layouts: unknown[] = []
  level = 1
  readonly fit = vi.fn(() => {
    this.level = fitting.zoom
  })
  readonly center = vi.fn()
  readonly destroy = vi.fn()
  readonly png = vi.fn<(options: unknown) => string>(() => 'data:image/png;base64,AAAA')

  constructor(readonly options: { container: HTMLElement; elements: ElementDefinition[] }) {
    this.setElements(options.elements)
  }

  private setElements(elements: ElementDefinition[]): void {
    this.current = elements
    this.classes.clear()
    for (const element of elements.filter((entry) => entry.group === 'nodes')) {
      this.classes.set(element.data.id!, new Set(String(element.classes ?? '').split(/\s+/).filter(Boolean)))
    }
  }

  on(event: string, _selector: string, handler: Handler): void {
    this.handlers.set(event, handler)
  }

  tap(id: string): void {
    this.handlers.get('tap')?.({ target: { id: () => id, hasClass: (name) => this.hasClass(id, name) } })
  }

  zoom(level?: number | { level: number }): number {
    if (level !== undefined) this.level = typeof level === 'number' ? level : level.level
    return this.level
  }

  width(): number {
    return 800
  }

  height(): number {
    return 600
  }

  batch(work: () => void): void {
    work()
  }

  nodes() {
    return [...this.classes.keys()].map((id) => ({
      id: () => id,
      hasClass: (name: string) => this.hasClass(id, name),
      toggleClass: (name: string, on: boolean) => {
        const set = this.classes.get(id)!
        if (on) set.add(name)
        else set.delete(name)
      },
    }))
  }

  elements() {
    return { remove: () => this.classes.clear() }
  }

  add(elements: ElementDefinition[]): void {
    this.setElements(elements)
  }

  layout(options: unknown) {
    this.layouts.push(options)
    return { run: vi.fn() }
  }

  hasClass(id: string, name: string): boolean {
    return this.classes.get(id)?.has(name) ?? false
  }
}

/** The zoom a fit settles on: the real one depends on the size of the laid-out graph. */
export const fitting = { zoom: 1 }

export const instances: FakeCytoscape[] = []

export function createCytoscape(options: ConstructorParameters<typeof FakeCytoscape>[0]): FakeCytoscape {
  const instance = new FakeCytoscape(options)
  instances.push(instance)
  return instance
}
