import { mount, type VueWrapper } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { HistogramBucket, HistogramDetection } from '@/api'
import Timeline from '@/components/Timeline.vue'
import { LANE_ORDER } from '@/services/lanes'
import { GUTTER_WIDTH, computeLayout, type SceneData } from '@/services/timeline-layout'
import type { Span } from '@/services/timeline-scale'
import { eventFixture } from './events-fixtures'
import { RecordingContext } from './recording-context'

const WIDTH = GUTTER_WIDTH + 1000
const HEIGHT = 260
const LAYOUT = computeLayout(WIDTH, HEIGHT)
const VIEW: Span = { start: 0, end: 1000 }
const px = (time: number): number => GUTTER_WIDTH + time
const laneY = (lane: string): number => LAYOUT.lanes[LANE_ORDER.indexOf(lane)]!.centre
const AXIS_Y = LAYOUT.axis.top + LAYOUT.axis.height / 2
const PLOT_Y = laneY('registry')

const event = (time: number, lane: string, id: string, summary = `summary ${id}`) => eventFixture({ id, time: new Date(time).toISOString(), lane, summary })
const bucket = (time: number, byLane: Record<string, number>): HistogramBucket => ({ time: new Date(time).toISOString(), total: 1, by_lane: byLane })
const alert = (time: number, id = 'd1'): HistogramDetection => ({ time: new Date(time).toISOString(), id, name: 'injection_rule', severity: 'high', ruleset: 'cape' })

const EVENTS: SceneData = {
  mode: 'events',
  events: [event(300, 'file', 'a', 'wrote report.docx'), ...Array.from({ length: 5 }, (_, index) => event(500 + index, 'api', `c${index}`))],
  detections: [alert(700)],
}
const BARS: SceneData = { mode: 'buckets', buckets: [bucket(200, { file: 1500 })], intervalMs: 100, detections: [] }

let context: RecordingContext
let wrapper: VueWrapper
let wrappers: VueWrapper[] = []
let observers: { callback: ResizeObserverCallback }[] = []

type Props = Partial<{
  view: Span
  full: Span
  data: SceneData | undefined
  chip: Span | null
  selectedId: string | null
  selectedTime: number | null
  loading: boolean
}>

async function show(props: Props = {}) {
  wrapper = mount(Timeline, {
    attachTo: document.body,
    props: { view: VIEW, full: { start: 0, end: 10_000 }, data: EVENTS, chip: null, selectedId: null, selectedTime: null, loading: false, height: HEIGHT, ...props },
    global: { plugins: [Quasar] },
  })
  wrappers.push(wrapper)
  await wrapper.vm.$nextTick()
  return wrapper
}

const canvas = (): HTMLCanvasElement => wrapper.find('canvas').element

function pointer(type: string, x: number, y: number, init: PointerEventInit = {}): PointerEvent {
  const event = new PointerEvent(type, { clientX: x, clientY: y, button: 0, pointerId: 1, bubbles: true, cancelable: true, ...init })
  canvas().dispatchEvent(event)
  return event
}

function drag(from: [number, number], to: [number, number]): void {
  pointer('pointerdown', ...from)
  pointer('pointermove', ...to)
  pointer('pointerup', ...to)
}

function emitted<T = unknown>(name: string): T[] {
  return (wrapper.emitted(name) ?? []).map((args) => args[0] as T)
}

beforeEach(() => {
  context = new RecordingContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D)
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, right: WIDTH, bottom: HEIGHT, width: WIDTH, height: HEIGHT, x: 0, y: 0, toJSON: () => ({}) })
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
    callback(0)
    return 1
  })
  observers = []
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(callback: ResizeObserverCallback) {
        observers.push({ callback })
      }
      observe(): void {}
      disconnect(): void {}
    },
  )
  document.documentElement.style.setProperty('--dark-bg', 'rgb(10, 10, 10)')
  Object.defineProperty(window, 'devicePixelRatio', { value: 1, configurable: true })
})

afterEach(() => {
  for (const mounted of wrappers) mounted.unmount()
  wrappers = []
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('the canvas', () => {
  it('is focusable and named for assistive technology, with the keys it answers to', async () => {
    await show()
    const element = canvas()
    expect(element.getAttribute('tabindex')).toBe('0')
    expect(element.getAttribute('aria-label')).toMatch(/timeline/i)
    expect(element.getAttribute('aria-description') ?? '').toMatch(/arrow/i)
  })

  it('is as large as the layout, in device pixels', async () => {
    Object.defineProperty(window, 'devicePixelRatio', { value: 2, configurable: true })
    await show()
    expect(canvas().width).toBe(WIDTH * 2)
    expect(canvas().height).toBe(HEIGHT * 2)
    expect(canvas().style.width).toBe(`${WIDTH}px`)
    expect(context.ops.some((op) => op.name === 'setTransform' && op.args[0] === 2 && op.args[3] === 2)).toBe(true)
  })

  it('paints with the colours of the design tokens, read from the stylesheet', async () => {
    await show()
    const first = context.ops.find((op) => op.name === 'fillRect')!
    expect(first.fillStyle).toBe('rgb(10, 10, 10)')
  })

  it('repaints when the data changes, and when the size does', async () => {
    await show()
    const before = context.ops.length
    await wrapper.setProps({ data: BARS })
    expect(context.ops.length).toBeGreaterThan(before)
    const afterData = context.ops.length
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, right: 700, bottom: HEIGHT, width: 700, height: HEIGHT, x: 0, y: 0, toJSON: () => ({}) })
    observers[0]!.callback([], {} as ResizeObserver)
    await wrapper.vm.$nextTick()
    expect(canvas().width).toBe(700)
    expect(context.ops.length).toBeGreaterThan(afterData)
  })

  it('batches repaints into one animation frame', async () => {
    const frames: FrameRequestCallback[] = []
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => frames.push(callback))
    await show()
    frames.splice(0).forEach((callback) => callback(0))
    await wrapper.setProps({ data: BARS })
    await wrapper.setProps({ chip: { start: 100, end: 200 } })
    expect(frames).toHaveLength(1)
  })

  it('does not fail when the browser gives no drawing context', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    await expect(show()).resolves.toBeDefined()
  })
})

describe('the gutter', () => {
  it('names the detection track and the six lanes in the fixed order, each with its icon', async () => {
    await show()
    const labels = wrapper.findAll('.timeline__gutter-label').map((label) => label.text())
    expect(labels).toEqual(['DETECTIONS', 'PROCESS', 'FILE', 'REGISTRY', 'NETWORK', 'MEMORY', 'API', 'UTC'])
    expect(wrapper.findAll('.timeline__gutter-row .q-icon')).toHaveLength(7)
  })

  it('has each row at the height and offset of its lane on the canvas', async () => {
    await show()
    const rows = wrapper.findAll('.timeline__gutter-row')
    expect(rows[2]!.attributes('style')).toContain(`top: ${LAYOUT.lanes[1]!.top}px`)
    expect(rows[2]!.attributes('style')).toContain(`height: ${LAYOUT.lanes[1]!.height}px`)
  })
})

describe('hovering', () => {
  it('shows the tooltip of an event mark: its summary, time and lane', async () => {
    await show()
    pointer('pointermove', px(300), laneY('file'))
    await wrapper.vm.$nextTick()
    const tip = wrapper.find('.timeline__tooltip')
    expect(tip.exists()).toBe(true)
    expect(tip.text()).toContain('wrote report.docx')
    expect(tip.text()).toContain('00:00:00.300')
    expect(tip.find('.q-icon').exists()).toBe(true)
  })

  it('shows the count and time span of a bar', async () => {
    await show({ data: BARS })
    pointer('pointermove', px(250), laneY('file'))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.timeline__tooltip').text()).toContain('1,500 FILE events')
    expect(wrapper.find('.timeline__tooltip').text()).toContain('00:00:00.200 - 00:00:00.300')
  })

  it('shows the name, severity and ruleset of a detection', async () => {
    await show()
    pointer('pointermove', px(700), LAYOUT.detectionTrack.centre)
    await wrapper.vm.$nextTick()
    const tip = wrapper.find('.timeline__tooltip')
    expect(tip.text()).toContain('injection_rule')
    expect(tip.text()).toContain('HIGH')
    expect(tip.text()).toContain('cape')
  })

  it('goes away when the pointer moves off, or leaves the canvas', async () => {
    await show()
    pointer('pointermove', px(300), laneY('file'))
    await wrapper.vm.$nextTick()
    pointer('pointermove', px(400), laneY('file'))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.timeline__tooltip').exists()).toBe(false)
    pointer('pointermove', px(300), laneY('file'))
    pointer('pointerleave', px(300), laneY('file'))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.timeline__tooltip').exists()).toBe(false)
  })

  it('opens toward the middle of the canvas, so it stays on it', async () => {
    await show()
    pointer('pointermove', px(700), LAYOUT.detectionTrack.centre)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.timeline__tooltip').attributes('style')).toContain('right:')
  })

  it('has no tooltip over empty plot, the axis or the gutter', async () => {
    await show()
    for (const [x, y] of [[px(100), PLOT_Y], [px(100), AXIS_Y], [20, PLOT_Y]]) {
      pointer('pointermove', x!, y!)
      await wrapper.vm.$nextTick()
      expect(wrapper.find('.timeline__tooltip').exists()).toBe(false)
    }
  })

  it('changes the cursor to say what a press would do', async () => {
    await show()
    pointer('pointermove', px(300), laneY('file'))
    await wrapper.vm.$nextTick()
    expect(canvas().className).toContain('is-pointer')
    pointer('pointermove', px(100), PLOT_Y)
    await wrapper.vm.$nextTick()
    expect(canvas().className).toContain('is-grab')
    pointer('pointermove', px(100), AXIS_Y)
    await wrapper.vm.$nextTick()
    expect(canvas().className).toContain('is-crosshair')
  })
})

describe('clicking', () => {
  it('on an event mark opens that event', async () => {
    await show()
    drag([px(300), laneY('file')], [px(300), laneY('file')])
    expect(emitted('open-event')).toEqual(['a'])
  })

  it('on a detection opens its event', async () => {
    await show()
    drag([px(700), LAYOUT.detectionTrack.centre], [px(700), LAYOUT.detectionTrack.centre])
    expect(emitted('open-event')).toEqual(['d1'])
  })

  it('on a bar zooms to its bucket', async () => {
    await show({ data: BARS })
    drag([px(250), laneY('file')], [px(250), laneY('file')])
    expect(emitted('navigate')).toEqual([{ kind: 'view', span: { start: 200, end: 300 } }])
  })

  it('on a count mark zooms in on the events it holds', async () => {
    await show()
    drag([px(502), laneY('api')], [px(502), laneY('api')])
    const [navigation] = emitted<{ kind: string; span: Span }>('navigate')
    expect(navigation!.kind).toBe('view')
    expect(navigation!.span.start).toBeLessThan(500)
    expect(navigation!.span.end).toBeGreaterThan(504)
  })

  it('on a count mark of events at one instant opens the first of them, since no zoom separates them', async () => {
    const same = Array.from({ length: 6 }, (_, index) => event(400, 'api', `s${index}`))
    await show({ data: { mode: 'events', events: same, detections: [] } })
    drag([px(400), laneY('api')], [px(400), laneY('api')])
    expect(emitted('open-event')).toEqual(['s0'])
    expect(emitted('navigate')).toEqual([])
  })

  it('on empty plot does nothing', async () => {
    await show()
    drag([px(100), PLOT_Y], [px(100), PLOT_Y])
    expect(wrapper.emitted('open-event')).toBeUndefined()
    expect(wrapper.emitted('navigate')).toBeUndefined()
  })

  it('twice resets the zoom to fit', async () => {
    await show()
    canvas().dispatchEvent(new MouseEvent('dblclick', { clientX: px(100), clientY: PLOT_Y, bubbles: true }))
    expect(emitted('navigate')).toEqual([{ kind: 'fit' }])
  })
})

describe('the wheel', () => {
  function wheel(deltaY: number, x: number, extra: { deltaX?: number } = {}): Event {
    const event = new WheelEvent('wheel', { deltaY, deltaX: extra.deltaX ?? 0, bubbles: true, cancelable: true })
    Object.defineProperty(event, 'clientX', { value: x })
    Object.defineProperty(event, 'clientY', { value: PLOT_Y })
    canvas().dispatchEvent(event)
    return event
  }

  it('zooms in around the time under the cursor when scrolled up', async () => {
    await show()
    wheel(-100, px(250))
    const [navigation] = emitted<{ kind: string; time: number; factor: number }>('navigate')
    expect(navigation!.kind).toBe('zoom')
    expect(navigation!.time).toBeCloseTo(250, 6)
    expect(navigation!.factor).toBeLessThan(1)
  })

  it('zooms out when scrolled down', async () => {
    await show()
    wheel(100, px(250))
    expect(emitted<{ factor: number }>('navigate')[0]!.factor).toBeGreaterThan(1)
  })

  it('keeps the page from scrolling', async () => {
    await show()
    expect(wheel(-100, px(250)).defaultPrevented).toBe(true)
  })

  it('zooms around the middle of the view when the cursor is over the gutter', async () => {
    await show()
    wheel(-100, 20)
    expect(emitted<{ time: number }>('navigate')[0]!.time).toBe(500)
  })

  it('pans on a horizontal scroll', async () => {
    await show()
    wheel(0, px(250), { deltaX: 40 })
    expect(emitted('navigate')).toEqual([{ kind: 'pan-pixels', dx: -40, width: 1000 }])
  })
})

describe('dragging in the lanes', () => {
  it('pans by the distance dragged, as it goes', async () => {
    await show()
    pointer('pointerdown', px(500), PLOT_Y)
    pointer('pointermove', px(520), PLOT_Y)
    pointer('pointermove', px(530), PLOT_Y)
    pointer('pointerup', px(530), PLOT_Y)
    expect(emitted('navigate')).toEqual([
      { kind: 'pan-pixels', dx: 20, width: 1000 },
      { kind: 'pan-pixels', dx: 10, width: 1000 },
    ])
    expect(wrapper.emitted('open-event')).toBeUndefined()
  })

  it('does not open an event when a drag that started on a mark ends', async () => {
    await show()
    drag([px(300), laneY('file')], [px(340), laneY('file')])
    expect(wrapper.emitted('open-event')).toBeUndefined()
  })
})

describe('brushing on the axis', () => {
  it('selects the dragged range when the button is released', async () => {
    await show()
    drag([px(200), AXIS_Y], [px(450), AXIS_Y])
    expect(emitted('select-range')).toEqual([{ start: 200, end: 450 }])
  })

  it('selects nothing for a click on the axis', async () => {
    await show()
    drag([px(200), AXIS_Y], [px(201), AXIS_Y])
    expect(wrapper.emitted('select-range')).toBeUndefined()
  })

  it('draws the brushed band and its label while dragging', async () => {
    await show()
    pointer('pointerdown', px(200), AXIS_Y)
    pointer('pointermove', px(450), AXIS_Y)
    await wrapper.vm.$nextTick()
    expect(context.ops.some((op) => op.name === 'fillText' && String(op.args[0]).startsWith('00:00:00.200 - 00:00:00.450'))).toBe(true)
    pointer('pointerup', px(450), AXIS_Y)
  })

  it('is called off by Escape: nothing is selected on release', async () => {
    await show()
    pointer('pointerdown', px(200), AXIS_Y)
    pointer('pointermove', px(450), AXIS_Y)
    canvas().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    pointer('pointerup', px(450), AXIS_Y)
    expect(wrapper.emitted('select-range')).toBeUndefined()
    expect(wrapper.emitted('clear-range')).toBeUndefined()
  })
})

describe('the time-range chip', () => {
  const chip: Span = { start: 200, end: 600 }

  it('is drawn as a band over the plot', async () => {
    await show({ chip })
    const band = context.ops.find((op) => op.name === 'fillRect' && op.alpha < 1 && op.args[0] === px(200))
    expect(band).toBeDefined()
  })

  it('has handles that move its ends', async () => {
    await show({ chip })
    drag([px(600), AXIS_Y], [px(800), AXIS_Y])
    expect(emitted('select-range')).toEqual([{ start: 200, end: 800 }])
  })

  it('is cleared by Escape on the canvas when nothing is being dragged', async () => {
    await show({ chip })
    canvas().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(wrapper.emitted('clear-range')).toHaveLength(1)
  })
})

describe('the keyboard', () => {
  function press(key: string, init: KeyboardEventInit = {}): KeyboardEvent {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init })
    canvas().dispatchEvent(event)
    return event
  }

  it.each([
    ['ArrowLeft', { kind: 'pan-fraction', fraction: -0.25 }],
    ['ArrowRight', { kind: 'pan-fraction', fraction: 0.25 }],
    ['+', { kind: 'zoom', time: 500, factor: 0.5 }],
    ['-', { kind: 'zoom', time: 500, factor: 2 }],
    ['0', { kind: 'fit' }],
    ['Home', { kind: 'jump', edge: 'start' }],
    ['End', { kind: 'jump', edge: 'end' }],
  ])('%s', async (key, navigation) => {
    await show()
    press(key)
    expect(emitted('navigate')).toEqual([navigation])
  })

  it('zooms around the selected event when it is in view', async () => {
    await show({ selectedTime: 300 })
    press('+')
    expect(emitted<{ time: number }>('navigate')[0]!.time).toBe(300)
  })

  it('keeps the keys it handles from also scrolling the page', async () => {
    await show()
    expect(press('ArrowRight').defaultPrevented).toBe(true)
    expect(press('a').defaultPrevented).toBe(false)
  })
})

describe('the states drawn over the canvas', () => {
  it('says so when the view holds no events', async () => {
    await show({ data: { mode: 'events', events: [], detections: [] } })
    expect(wrapper.find('.timeline__empty').text()).toContain('no events in this range')
  })

  it('does not say so while there are events, or before any data', async () => {
    await show()
    expect(wrapper.find('.timeline__empty').exists()).toBe(false)
    await show({ data: undefined })
    expect(wrapper.find('.timeline__empty').exists()).toBe(false)
  })

  it('shows a progress line while the next range loads', async () => {
    await show()
    expect(wrapper.find('.timeline__loading').exists()).toBe(false)
    await wrapper.setProps({ loading: true })
    expect(wrapper.find('.timeline__loading').exists()).toBe(true)
  })
})

describe('what the root says about the scene, for the screenshot and end-to-end tests to aim at', () => {
  it('names the source and counts what is drawn', async () => {
    await show()
    expect(wrapper.attributes('data-source')).toBe('events')
    expect(wrapper.attributes('data-marks')).toBe('2')
    expect(wrapper.attributes('data-detections')).toBe('1')
    await wrapper.setProps({ data: BARS })
    expect(wrapper.attributes('data-source')).toBe('buckets')
    expect(wrapper.attributes('data-bars')).toBe('1')
  })

  it('gives the geometry a pointer needs to find a lane, the axis and a time', async () => {
    await show()
    const geometry = JSON.parse(wrapper.attributes('data-geometry')!)
    expect(geometry).toMatchObject({ gutter: GUTTER_WIDTH, plotWidth: 1000, viewStart: 0, viewEnd: 1000, axisY: AXIS_Y, detectionY: LAYOUT.detectionTrack.centre })
    expect(geometry.lanes.file).toBe(laneY('file'))
  })
})
