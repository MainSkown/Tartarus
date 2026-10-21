import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { QueueSnapshot, RunningAnalysis } from '@/api'
import LiveChip from '@/components/LiveChip.vue'

const NOW = Date.parse('2026-10-21T10:01:12Z')

vi.mock('@/api', () => ({ systemQueue: vi.fn() }))
const system = { onQueue: vi.fn(() => () => undefined) }
vi.mock('@/stores/system', () => ({ useSystemStore: () => system }))

const { systemQueue } = await import('@/api')

function running(id: number, filename: string, guest: string | null, startedAt = '2026-10-21T10:00:00Z'): RunningAnalysis {
  return { id, filename, guest, status: 'running', started_at: startedAt, elapsed_s: null }
}

async function mountWith(runningItems: RunningAnalysis[], queuedCount = 0) {
  const snapshot: QueueSnapshot = { running: runningItems, queued_count: queuedCount, queued: [] }
  vi.mocked(systemQueue).mockResolvedValue({ data: snapshot } as never)
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/analyses/:id', name: 'analysis-workspace', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  const wrapper = mount(LiveChip, { global: { plugins: [Quasar, pinia, router] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
  vi.mocked(systemQueue).mockReset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('LiveChip', () => {
  it('renders nothing when no analysis is running', async () => {
    const wrapper = await mountWith([])
    expect(wrapper.find('.live-chip').exists()).toBe(false)
  })

  it('shows one running analysis as LIVE #id with its clock, linking to it', async () => {
    const wrapper = await mountWith([running(42, 'invoice.exe', 'lab1')])
    const chip = wrapper.find('.live-chip')
    expect(chip.text()).toBe('LIVE #42 01:12')
    expect(chip.attributes('href')).toBe('/analyses/42')
    expect(wrapper.find('.live-chip-menu').exists()).toBe(false)
  })

  it('shows several running analyses as a count, with a menu listing each', async () => {
    const wrapper = await mountWith([
      running(41, 'dropper.dll', 'lab1'),
      running(42, 'invoice.exe', 'lab2'),
      running(43, 'macro.doc', null),
    ])
    expect(wrapper.find('.live-chip').text()).toBe('LIVE 3')
    expect(wrapper.find('.live-chip').attributes('href')).toBeUndefined()

    await wrapper.find('.live-chip').trigger('click')
    await flushPromises()
    const items = document.querySelectorAll('.live-chip-menu__item')
    expect(items).toHaveLength(3)
    expect(items[1]?.textContent).toContain('invoice.exe')
    expect(items[1]?.textContent).toContain('lab2')
    expect(items[1]?.getAttribute('href')).toBe('/analyses/42')
    wrapper.unmount()
  })

  it('counts each clock on from its start, so it keeps moving', async () => {
    const wrapper = await mountWith([running(42, 'invoice.exe', 'lab1')])
    await vi.advanceTimersByTimeAsync(3_000)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.live-chip').text()).toBe('LIVE #42 01:15')
  })
})
