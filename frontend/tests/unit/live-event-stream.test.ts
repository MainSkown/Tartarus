import { mount } from '@vue/test-utils'
import { Quasar, QVirtualScroll } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import LiveEventStream from '@/components/LiveEventStream.vue'
import { NO_FILTER } from '@/services/live-state'
import { liveEvent } from './live-fixtures'

const EVENTS = [
  liveEvent({ id: 'a', lane: 'file' }),
  liveEvent({ id: 'b', lane: 'network', pid: 2476, process: { pid: 2476, name: 'cmd.exe' }, '@timestamp': '2026-10-13T15:39:51.007Z' }),
  liveEvent({ id: 'c', lane: 'registry', process: undefined }),
]

type Props = InstanceType<typeof LiveEventStream>['$props']

function mountStream(props: Partial<Props> = {}) {
  return mount(LiveEventStream, {
    global: { plugins: [Quasar] },
    props: {
      events: EVENTS,
      paused: false,
      backlog: 0,
      filter: NO_FILTER,
      dropped: 0,
      trimmed: 0,
      emptyMessage: 'connected, no events yet',
      ...props,
    },
  })
}

describe('LiveEventStream rows', () => {
  it('shows the time, the lane, the process and the summary of each event', () => {
    const rows = mountStream().findAll('.live-event')
    expect(rows).toHaveLength(3)
    expect(rows[0]!.find('.live-event__time').text()).toBe('15:39:50.412')
    expect(rows[0]!.find('.live-event__lane').text()).toBe('FILE')
    expect(rows[0]!.find('.process-chip').text()).toBe('benign.exe (9708)')
    expect(rows[0]!.find('.live-event__summary').text()).toContain('benign.exe wrote')
    expect(rows[1]!.find('.live-event__lane').text()).toBe('NETWORK')
    expect(rows[1]!.find('.process-chip').text()).toBe('cmd.exe (2476)')
  })

  it('draws the lane icon beside its label', () => {
    const row = mountStream().findAll('.live-event')[0]!
    expect(row.find('.q-icon').text()).toBe('description')
  })

  it('shows a dash for an event that names no process', () => {
    expect(mountStream().findAll('.live-event')[2]!.find('.process-chip').text()).toBe('–')
  })

  it('says why there are no events', () => {
    const wrapper = mountStream({ events: [], emptyMessage: 'starting the guest...' })
    expect(wrapper.find('.live-event').exists()).toBe(false)
    expect(wrapper.find('.live-stream__empty').text()).toContain('starting the guest...')
  })
})

describe('LiveEventStream filters', () => {
  it('offers a chip for every lane but the noisy api lane', () => {
    const chips = mountStream().findAll('.live-stream__lane')
    expect(chips.map((chip) => chip.find('.live-stream__lane-label').text())).toEqual(['PROCESS', 'FILE', 'REGISTRY', 'NETWORK', 'MEMORY'])
  })

  it('asks for a lane when its chip is clicked, and shows it pressed', async () => {
    const wrapper = mountStream()
    await wrapper.findAll('.live-stream__lane')[1]!.trigger('click')
    expect(wrapper.emitted('filter')).toEqual([[{ lanes: ['file'] }]])

    await wrapper.setProps({ filter: { ...NO_FILTER, lanes: ['file'] } })
    expect(wrapper.findAll('.live-stream__lane').map((chip) => chip.attributes('aria-pressed'))).toEqual([
      'false',
      'true',
      'false',
      'false',
      'false',
    ])
  })

  it('adds a lane to the chosen ones and removes it on a second click', async () => {
    const wrapper = mountStream({ filter: { ...NO_FILTER, lanes: ['file'] } })
    await wrapper.findAll('.live-stream__lane')[3]!.trigger('click')
    await wrapper.findAll('.live-stream__lane')[1]!.trigger('click')
    expect(wrapper.emitted('filter')).toEqual([[{ lanes: ['file', 'network'] }], [{ lanes: [] }]])
  })

  it('switches API calls on and off', async () => {
    const wrapper = mountStream()
    const toggle = wrapper.find('.live-stream__api input')
    expect((toggle.element as HTMLInputElement).checked).toBe(false)
    await toggle.setValue(true)
    expect(wrapper.emitted('filter')).toEqual([[{ includeApi: true }]])
  })

  it('shows API calls as on when the filter says so', () => {
    const wrapper = mountStream({ filter: { ...NO_FILTER, includeApi: true } })
    expect((wrapper.find('.live-stream__api input').element as HTMLInputElement).checked).toBe(true)
  })
})

describe('LiveEventStream pause', () => {
  it('asks to pause', async () => {
    const wrapper = mountStream()
    await wrapper.find('.live-stream__pause').trigger('click')
    expect(wrapper.emitted('pause')).toHaveLength(1)
  })

  it('offers to resume, with the count of events that arrived meanwhile', async () => {
    const wrapper = mountStream({ paused: true, backlog: 1204 })
    const button = wrapper.find('.live-stream__pause')
    expect(button.text()).toContain('RESUME')
    expect(button.text()).toContain('+1,204 new')
    await button.trigger('click')
    expect(wrapper.emitted('resume')).toHaveLength(1)
    expect(wrapper.emitted('pause')).toBeUndefined()
  })

  it('shows no counter while nothing arrived during the pause', () => {
    expect(mountStream({ paused: true, backlog: 0 }).find('.live-stream__pause').text()).not.toContain('new')
  })
})

describe('LiveEventStream banners', () => {
  it('says how many events the server skipped', () => {
    const wrapper = mountStream({ dropped: 1530 })
    expect(wrapper.find('.live-stream__skipped').text()).toContain('1,530 events skipped by the server, open table')
  })

  it('says how many older events the browser let go', () => {
    const wrapper = mountStream({ trimmed: 250 })
    expect(wrapper.find('.live-stream__trimmed').text()).toContain('250 older events trimmed')
  })

  it('shows neither banner when nothing was skipped or trimmed', () => {
    const wrapper = mountStream()
    expect(wrapper.find('.live-stream__skipped').exists()).toBe(false)
    expect(wrapper.find('.live-stream__trimmed').exists()).toBe(false)
  })

  it('writes a single skipped event in the singular', () => {
    expect(mountStream({ dropped: 1 }).find('.live-stream__skipped').text()).toContain('1 event skipped')
  })
})

describe('LiveEventStream follow', () => {
  function scrolled(wrapper: ReturnType<typeof mountStream>, direction: 'increase' | 'decrease', to: number) {
    wrapper.findComponent(QVirtualScroll).vm.$emit('virtual-scroll', { index: 0, from: 0, to, direction, ref: {} })
    return nextTick()
  }

  it('follows by default', () => {
    expect(mountStream().find('.live-stream__follow').attributes('aria-pressed')).toBe('true')
  })

  it('stops following when toggled off, and starts again when toggled on', async () => {
    const wrapper = mountStream()
    await wrapper.find('.live-stream__follow').trigger('click')
    expect(wrapper.find('.live-stream__follow').attributes('aria-pressed')).toBe('false')
    await wrapper.find('.live-stream__follow').trigger('click')
    expect(wrapper.find('.live-stream__follow').attributes('aria-pressed')).toBe('true')
  })

  it('stops following when the user scrolls up from the end', async () => {
    const wrapper = mountStream()
    await scrolled(wrapper, 'decrease', 0)
    expect(wrapper.find('.live-stream__follow').attributes('aria-pressed')).toBe('false')
  })

  it('does not stop following for the scroll that carries it down', async () => {
    const wrapper = mountStream()
    await scrolled(wrapper, 'increase', 1)
    expect(wrapper.find('.live-stream__follow').attributes('aria-pressed')).toBe('true')
  })

  it('follows again once the user scrolls back to the newest event', async () => {
    const wrapper = mountStream()
    await scrolled(wrapper, 'decrease', 0)
    await scrolled(wrapper, 'increase', EVENTS.length - 1)
    expect(wrapper.find('.live-stream__follow').attributes('aria-pressed')).toBe('true')
  })

  function listOf(wrapper: ReturnType<typeof mountStream>): HTMLElement {
    const list = wrapper.findComponent(QVirtualScroll).element as HTMLElement
    Object.defineProperty(list, 'scrollHeight', { value: 500, configurable: true })
    return list
  }

  it('scrolls to the end of the list as events arrive while following', async () => {
    const wrapper = mountStream()
    const list = listOf(wrapper)
    await wrapper.setProps({ events: [...EVENTS, liveEvent({ id: 'd' })] })
    expect(list.scrollTop).toBe(500)
  })

  it('leaves the list where it is when not following', async () => {
    const wrapper = mountStream()
    await wrapper.find('.live-stream__follow').trigger('click')
    const list = listOf(wrapper)
    list.scrollTop = 40
    await wrapper.setProps({ events: [...EVENTS, liveEvent({ id: 'd' })] })
    expect(list.scrollTop).toBe(40)
  })

  describe('when the space around it changes', () => {
    let observed: (() => void)[]

    beforeEach(() => {
      observed = []
      vi.stubGlobal(
        'ResizeObserver',
        class {
          constructor(callback: () => void) {
            observed.push(callback)
          }

          observe(): void {}
          disconnect(): void {}
        },
      )
    })

    afterEach(() => {
      vi.unstubAllGlobals()
    })

    it('stays at the newest event while following', async () => {
      const wrapper = mountStream()
      const list = listOf(wrapper)
      list.scrollTop = 0
      observed.forEach((callback) => callback())
      expect(list.scrollTop).toBe(500)
    })

    it('does not move the list when not following', async () => {
      const wrapper = mountStream()
      await wrapper.find('.live-stream__follow').trigger('click')
      const list = listOf(wrapper)
      list.scrollTop = 40
      observed.forEach((callback) => callback())
      expect(list.scrollTop).toBe(40)
    })
  })
})
