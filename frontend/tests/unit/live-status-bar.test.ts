import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LiveStatusBar from '@/components/LiveStatusBar.vue'

const NOW = new Date('2026-10-13T15:40:00Z').getTime()
const LIVE = { status: 'running', phase: 'live', elapsed_s: 72, remaining_s: 108, receivedAt: NOW } as const

type Props = InstanceType<typeof LiveStatusBar>['$props']

function mountBar(props: Partial<Props> = {}, actions = '') {
  return mount(LiveStatusBar, {
    global: { plugins: [Quasar] },
    slots: { actions },
    props: {
      status: 'running',
      live: LIVE,
      connection: 'open',
      ended: false,
      total: 12431,
      eventsPerMinute: 3202,
      queuePosition: null,
      ...props,
    },
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})

afterEach(() => {
  vi.useRealTimers()
})

describe('LiveStatusBar', () => {
  it('shows the state, the elapsed and the remaining time', () => {
    const wrapper = mountBar()
    expect(wrapper.find('.status-badge').text()).toContain('RUNNING')
    expect(wrapper.find('[data-field="elapsed"]').text()).toContain('1m 12s')
    expect(wrapper.find('[data-field="remaining"]').text()).toContain('1m 48s')
  })

  it('counts on between server updates, elapsed up and remaining down', async () => {
    const wrapper = mountBar()
    await vi.advanceTimersByTimeAsync(5_000)
    expect(wrapper.find('[data-field="elapsed"]').text()).toContain('1m 17s')
    expect(wrapper.find('[data-field="remaining"]').text()).toContain('1m 43s')
  })

  it('starts again from the figures of a new server update', async () => {
    const wrapper = mountBar()
    await vi.advanceTimersByTimeAsync(5_000)
    await wrapper.setProps({ live: { ...LIVE, elapsed_s: 80, remaining_s: 100, receivedAt: Date.now() } })
    expect(wrapper.find('[data-field="elapsed"]').text()).toContain('1m 20s')
  })

  it('does not let the remaining time go below zero', async () => {
    const wrapper = mountBar({ live: { ...LIVE, remaining_s: 2 } })
    await vi.advanceTimersByTimeAsync(10_000)
    expect(wrapper.find('[data-field="remaining"]').text()).toContain('0s')
  })

  it('stops counting when the analysis is no longer running', async () => {
    const wrapper = mountBar({ status: 'processing', live: { ...LIVE, status: 'processing' } })
    await vi.advanceTimersByTimeAsync(5_000)
    expect(wrapper.find('[data-field="elapsed"]').text()).toContain('1m 12s')
  })

  it('shows a dash for a time the server did not give', () => {
    const wrapper = mountBar({ live: undefined })
    expect(wrapper.find('[data-field="elapsed"]').text()).toContain('–')
    expect(wrapper.find('[data-field="remaining"]').text()).toContain('–')
  })

  it('shows the total events and the rate', () => {
    const wrapper = mountBar()
    expect(wrapper.find('[data-field="events"]').text()).toContain('12,431 events')
    expect(wrapper.find('[data-field="events"]').text()).toContain('3,202/min')
  })

  it('says how many of the events are in the stream when the stream shows fewer', () => {
    const wrapper = mountBar({ total: 481, listed: 8 })
    expect(wrapper.find('[data-field="events"]').text()).toContain('481 events (8 shown)')
    expect(wrapper.find('[data-field="events"]').text()).toContain('3,202/min')
  })

  it('formats the shown count like the total', () => {
    expect(mountBar({ total: 12431, listed: 1204 }).find('[data-field="events"]').text()).toContain('12,431 events (1,204 shown)')
  })

  it.each([undefined, 12431])('says nothing extra when the stream shows all of them (listed: %s)', (shown) => {
    expect(mountBar({ listed: shown }).find('[data-field="events"]').text()).not.toContain('shown')
  })

  it('says where a queued analysis stands instead of timing it', () => {
    const wrapper = mountBar({ status: 'queued', live: undefined, queuePosition: 2 })
    expect(wrapper.find('.status-badge').text()).toContain('QUEUED')
    expect(wrapper.text()).toContain('position 2 in the queue')
    expect(wrapper.find('[data-field="elapsed"]').exists()).toBe(false)
  })

  it.each([
    ['connecting', 'CONNECTING'],
    ['open', 'CONNECTED'],
    ['reconnecting', 'RECONNECTING'],
    ['closed', 'CLOSED'],
  ] as const)('writes the live socket state %s as %s', (connection, label) => {
    expect(mountBar({ connection }).find('[data-field="link"]').text()).toContain(label)
  })

  it('says the stream ended once the run is over, whatever the socket state', () => {
    const wrapper = mountBar({ status: 'done', ended: true, connection: 'closed' })
    expect(wrapper.find('[data-field="link"]').text()).toContain('STREAM ENDED')
  })

  it('warns in the last 30 seconds of an interactive run and says ending once it is out', async () => {
    const wrapper = mountBar({ interactive: true, live: { ...LIVE, remaining_s: 31 } })
    expect(wrapper.find('[data-field="remaining"]').text()).toContain('31s')
    expect(wrapper.find('[data-field="remaining"] .run-countdown--warning').exists()).toBe(false)
    await vi.advanceTimersByTimeAsync(1_000)
    expect(wrapper.find('[data-field="remaining"] .run-countdown--warning').exists()).toBe(true)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(wrapper.find('[data-field="remaining"]').text()).toContain('ending')
  })

  it('jumps to the new figure when an extension raises the remaining time', async () => {
    const wrapper = mountBar({ interactive: true, live: { ...LIVE, remaining_s: 20 } })
    await vi.advanceTimersByTimeAsync(3_000)
    await wrapper.setProps({ live: { ...LIVE, remaining_s: 80, receivedAt: Date.now() } })
    expect(wrapper.find('[data-field="remaining"]').text()).toContain('1m 20s')
  })

  it('keeps the remaining time of a run that is not interactive as it was: no warning, no ending', async () => {
    const wrapper = mountBar({ live: { ...LIVE, remaining_s: 5 } })
    await vi.advanceTimersByTimeAsync(10_000)
    expect(wrapper.find('[data-field="remaining"]').text()).toContain('0s')
    expect(wrapper.find('.run-countdown--warning').exists()).toBe(false)
  })

  it('shows what is put in its actions slot after the event counter', () => {
    const wrapper = mountBar({}, '<button data-test="action">END</button>')
    const html = wrapper.html()
    expect(html.indexOf('data-test="action"')).toBeGreaterThan(html.indexOf('data-field="events"'))
  })
})
