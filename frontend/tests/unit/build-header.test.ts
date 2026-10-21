import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import BuildHeader from '@/components/guest/BuildHeader.vue'

const NOW = new Date('2026-10-21T12:10:00Z')
const DESCRIPTION = 'Windows installs itself. The desktop may look idle for minutes; that is normal.'

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})
afterEach(() => vi.useRealTimers())

function mountHeader(props: Record<string, unknown> = {}) {
  return mount(BuildHeader, {
    global: { plugins: [Quasar], stubs: { 'router-link': true } },
    props: {
      guest: 'w10',
      kind: 'build',
      phase: 'running',
      percent: 34,
      message: 'Windows is provisioning itself: install 32-bit Python 3.11',
      backLink: true,
      description: DESCRIPTION,
      lastActivity: '2026-10-21T12:09:48Z',
      ...props,
    },
  })
}

const text = (wrapper: ReturnType<typeof mountHeader>, hook: string) => wrapper.find(`[data-build="${hook}"]`)

describe('BuildHeader under the progress bar', () => {
  it('says what the running step is in the profile’s own sentence', () => {
    expect(text(mountHeader(), 'description').text()).toBe(DESCRIPTION)
  })

  it('says what is being done right now, from the build message, beside the percentage', () => {
    const wrapper = mountHeader()
    expect(text(wrapper, 'percent').text()).toBe('34%')
    expect(text(wrapper, 'message').text()).toBe('Windows is provisioning itself: install 32-bit Python 3.11')
  })

  it('shows how long ago the step last did anything, counting on each second', async () => {
    const wrapper = mountHeader()
    expect(text(wrapper, 'activity').text()).toBe('last activity 12s ago')
    await vi.advanceTimersByTimeAsync(3_000)
    expect(text(wrapper, 'activity').text()).toBe('last activity 15s ago')
    expect(text(wrapper, 'activity').attributes('data-stale')).toBe('false')
  })

  it('turns the age into a warning after two minutes without news', () => {
    const wrapper = mountHeader({ lastActivity: '2026-10-21T12:07:00Z' })
    const activity = text(wrapper, 'activity')
    expect(activity.text()).toContain('no news for 3 min: the step may be waiting or stuck')
    expect(activity.attributes('data-stale')).toBe('true')
    expect(activity.classes()).toContain('build-header__activity--stale')
  })

  it('leaves out what it has nothing to say about', () => {
    const wrapper = mountHeader({ description: null, lastActivity: null })
    expect(text(wrapper, 'description').exists()).toBe(false)
    expect(text(wrapper, 'activity').exists()).toBe(false)
  })
})
