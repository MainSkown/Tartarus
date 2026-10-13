import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisRead } from '@/api'
import { analysisWithStatus } from './analysis-fixtures'
import { FakeWebSocket } from './fake-websocket'
import { liveEvent, liveProcess } from './live-fixtures'

vi.mock('@/api', () => ({
  viewsArtifacts: vi.fn(() => Promise.resolve({ data: { screenshots: [{ n: 1, name: '1.jpg', size: 1 }] }, error: undefined })),
}))

// The desktop panel has its own tests; here it only has to be on the page, without opening a second socket.
vi.mock('@/services/desktop-guacamole', () => ({ loadGuacamole: () => new Promise(() => undefined) }))

const LiveTab = (await import('@/components/tabs/LiveTab.vue')).default
const LiveEventStream = (await import('@/components/LiveEventStream.vue')).default

const RUNNING = { status: 'running', phase: 'live', elapsed_s: 12, remaining_s: 168 }
const running = (overrides: Partial<AnalysisRead> = {}) => analysisWithStatus('running', { finished_at: null, ...overrides })
const socket = () => FakeWebSocket.latest

// A wrapper left mounted keeps its socket client, and a close in its test arms a reconnect timer that
// opens a new fake socket during some later test, which then talks to the wrong component.
const mounted: VueWrapper[] = []

async function mountTab(analysis: AnalysisRead = running()) {
  const wrapper = mount(LiveTab, { attachTo: document.body, global: { plugins: [Quasar] }, props: { analysis } })
  mounted.push(wrapper)
  socket().serverOpens()
  await flushPromises()
  return wrapper
}

async function send(type: string, data: unknown) {
  socket().serverSends(type, data)
  await flushPromises()
}

beforeEach(() => {
  FakeWebSocket.reset()
  vi.stubGlobal('WebSocket', FakeWebSocket)
})

afterEach(() => {
  mounted.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('LiveTab', () => {
  it('opens the live socket of the analysis it is given', async () => {
    await mountTab(running({ id: 45 }))
    expect(socket().url).toContain('/ws/analyses/45/live')
  })

  it('is the live tab, and fills the screen under the header', async () => {
    const wrapper = await mountTab()
    expect(wrapper.attributes('data-tab')).toBe('live')
    expect(wrapper.attributes('style')).toContain('--tab-fill-height')
  })

  it('closes the socket when the tab is left', async () => {
    const wrapper = await mountTab()
    wrapper.unmount()
    expect(socket().readyState).toBe(3)
  })

  it('composes the status bar, the process tree, the detections and the event stream', async () => {
    const wrapper = await mountTab()
    for (const part of ['status', 'processes', 'detections', 'stream']) {
      expect(wrapper.find(`[data-live="${part}"]`).exists(), part).toBe(true)
    }
  })
})

describe('LiveTab desktop slot', () => {
  it('has no desktop slot for a plain analysis', async () => {
    expect((await mountTab()).find('[data-live="desktop"]').exists()).toBe(false)
  })

  it('has the desktop slot for an interactive analysis', async () => {
    const wrapper = await mountTab(running({ options: { interactive: true } }))
    expect(wrapper.find('[data-live="desktop"]').exists()).toBe(true)
  })

  it('does not take a truthy string for interactive', async () => {
    const wrapper = await mountTab(running({ options: { interactive: 'yes' } }))
    expect(wrapper.find('[data-live="desktop"]').exists()).toBe(false)
  })
})

describe('LiveTab content', () => {
  it('shows the status from the server', async () => {
    const wrapper = await mountTab()
    await send('status', RUNNING)
    expect(wrapper.find('[data-field="elapsed"]').text()).toContain('12s')
    expect(wrapper.find('[data-field="link"]').text()).toContain('CONNECTED')
  })

  it('grows the process tree from deltas', async () => {
    const wrapper = await mountTab()
    await send('process', { op: 'add', node: liveProcess(10, { name: 'benign.exe' }) })
    await send('process', { op: 'add', node: liveProcess(11, { ppid: 10, name: 'cmd.exe' }) })
    expect(wrapper.findAll('.live-process').map((row) => row.find('.process-chip').text())).toEqual(['benign.exe (10)', 'cmd.exe (11)'])
  })

  it('lists the events that arrive', async () => {
    const wrapper = await mountTab()
    await send('events', { events: [liveEvent({ id: 'a' }), liveEvent({ id: 'b' })], dropped: 0 })
    expect(wrapper.findAll('.live-event')).toHaveLength(2)
  })

  it('filters the stream to a process when it is clicked in the tree, and clears it on a second click', async () => {
    const wrapper = await mountTab()
    await send('process', { op: 'add', node: liveProcess(10, { name: 'benign.exe' }) })
    await send('events', { events: [liveEvent({ id: 'a', pid: 10 }), liveEvent({ id: 'b', pid: 11 })], dropped: 0 })

    await wrapper.find('.live-process').trigger('click')
    expect(socket().subscribes.at(-1)).toEqual({ type: 'subscribe', data: { include_api: false, pids: [10] } })
    expect(wrapper.findAll('.live-event')).toHaveLength(1)

    await wrapper.find('.live-process').trigger('click')
    expect(socket().subscribes.at(-1)).toEqual({ type: 'subscribe', data: { include_api: false } })
    expect(wrapper.findAll('.live-event')).toHaveLength(2)
  })

  it('asks the server for API calls when the switch is turned on', async () => {
    const wrapper = await mountTab()
    await wrapper.find('.live-stream__api input').setValue(true)
    expect(socket().subscribes.at(-1)).toEqual({ type: 'subscribe', data: { include_api: true } })
  })

  it('pauses the stream, counting what arrives, and shows it on resume', async () => {
    const wrapper = await mountTab()
    const shown = () => wrapper.findComponent(LiveEventStream).props('events').length
    await send('events', { events: [liveEvent({ id: 'a' })], dropped: 0 })
    await wrapper.find('.live-stream__pause').trigger('click')
    await send('events', { events: [liveEvent({ id: 'b' }), liveEvent({ id: 'c' })], dropped: 0 })
    expect(shown()).toBe(1)
    expect(wrapper.find('.live-stream__pause').text()).toContain('+2 new')

    await wrapper.find('.live-stream__pause').trigger('click')
    expect(shown()).toBe(3)
  })

  it('says how many events the server skipped', async () => {
    const wrapper = await mountTab()
    await send('events', { events: [liveEvent()], dropped: 40 })
    expect(wrapper.find('.live-stream__skipped').text()).toContain('40 events skipped by the server')
  })

  it('shows the total from the server counts', async () => {
    const wrapper = await mountTab()
    await send('counts', { by_lane: { file: 3 }, by_severity: { info: 3 }, total: 12431 })
    expect(wrapper.find('[data-field="events"]').text()).toContain('12,431 events')
  })

  it('tells the total from what the stream lists when the two differ', async () => {
    const wrapper = await mountTab()
    await send('events', { events: [liveEvent({ id: 'a' }), liveEvent({ id: 'b' })], dropped: 0 })
    await send('counts', { by_lane: { file: 481 }, by_severity: { info: 481 }, total: 481 })
    expect(wrapper.find('[data-field="events"]').text()).toContain('481 events (2 shown)')
  })
})

describe('LiveTab waiting states', () => {
  it('says the guest is starting until the first process appears', async () => {
    const wrapper = await mountTab()
    expect(wrapper.find('[data-live="processes"]').text()).toContain('starting the guest...')
    expect(wrapper.find('.live-stream__empty').text()).toContain('starting the guest...')
  })

  it('says it is connected, with no events yet, once a process exists', async () => {
    const wrapper = await mountTab()
    await send('process', { op: 'add', node: liveProcess(10) })
    expect(wrapper.find('.live-stream__empty').text()).toContain('connected, no events yet')
  })

  it('says a queued analysis is queued, with its place', async () => {
    const wrapper = await mountTab(analysisWithStatus('queued', { started_at: null, finished_at: null, queue_position: 3 }))
    expect(wrapper.find('.live-stream__empty').text()).toContain('queued, position 3')
    expect(wrapper.find('[data-live="status"]').text()).toContain('position 3 in the queue')
  })

  it('says no event matches when a filter hides them all', async () => {
    const wrapper = await mountTab()
    await send('process', { op: 'add', node: liveProcess(10) })
    await wrapper.find('.live-process').trigger('click')
    expect(wrapper.find('.live-stream__empty').text()).toContain('no events match the filter')
  })
})

describe('LiveTab notices', () => {
  it('shows a server error as a notice that does not block the tab', async () => {
    const wrapper = await mountTab()
    await send('error', { code: 'live_index_failed', message: 'bulk rejected' })
    expect(wrapper.find('.live-tab__notices').text()).toContain('live indexing failed (bulk rejected)')
    expect(wrapper.find('[data-live="stream"]').exists()).toBe(true)
  })

  it('says the live stream does not know the analysis after close 4404', async () => {
    const wrapper = await mountTab()
    socket().serverCloses(4404)
    await flushPromises()
    expect(wrapper.find('.live-tab__notices').text()).toContain('the live stream does not know this analysis')
  })
})

describe('LiveTab reconnecting', () => {
  it('shows the state of its own socket in the status bar', async () => {
    const wrapper = await mountTab()
    socket().serverCloses(1006)
    await flushPromises()
    expect(wrapper.find('[data-field="link"]').text()).toContain('RECONNECTING')
  })
})

describe('LiveTab finished', () => {
  it('shows the finished panel instead of the detections when the stream says the run is over', async () => {
    const wrapper = await mountTab()
    await send('status', { status: 'done', phase: 'live', elapsed_s: 180, remaining_s: 0 })
    expect(wrapper.find('[data-live="finished"]').exists()).toBe(true)
    expect(wrapper.find('[data-live="detections"]').exists()).toBe(false)
    expect(wrapper.find('[data-field="link"]').text()).toContain('STREAM ENDED')
  })

  it('shows the finished panel when the polled analysis is already over', async () => {
    const wrapper = await mountTab(analysisWithStatus('done'))
    expect(wrapper.find('[data-live="finished"]').exists()).toBe(true)
  })

  it('keeps the tree and the events it had when the run ends', async () => {
    const wrapper = await mountTab()
    await send('process', { op: 'add', node: liveProcess(10) })
    await send('events', { events: [liveEvent({ id: 'a' })], dropped: 0 })
    await send('status', { status: 'done', phase: 'live', elapsed_s: 180, remaining_s: 0 })
    expect(wrapper.findAll('.live-process')).toHaveLength(1)
    expect(wrapper.findAll('.live-event')).toHaveLength(1)
  })

  it('shows the processes that never reported an end as ended', async () => {
    const wrapper = await mountTab()
    await send('process', { op: 'add', node: liveProcess(10) })
    await send('status', { status: 'done', phase: 'live', elapsed_s: 180, remaining_s: 0 })
    expect(wrapper.find('.live-process__state').text()).toBe('ended')
  })

  it('asks the page for the summary tab', async () => {
    const wrapper = await mountTab(analysisWithStatus('done'))
    await wrapper.find('.live-finished__summary').trigger('click')
    expect(wrapper.emitted('open-tab')).toEqual([['summary']])
  })

  it('reports the finished status in the bar even before the stream says so', async () => {
    const wrapper = await mountTab(analysisWithStatus('done'))
    expect(wrapper.find('.status-badge').text()).toContain('DONE')
  })
})
