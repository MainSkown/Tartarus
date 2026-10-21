import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import type { QueueSnapshot } from '@/api'
import QueuePosition from '@/components/QueuePosition.vue'

vi.mock('@/api', () => ({ systemQueue: vi.fn() }))
const system = { onQueue: vi.fn(() => () => undefined) }
vi.mock('@/stores/system', () => ({ useSystemStore: () => system }))

const { systemQueue } = await import('@/api')

async function mountFor(snapshot: QueueSnapshot, analysisId: number) {
  vi.mocked(systemQueue).mockResolvedValue({ data: snapshot } as never)
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(QueuePosition, { props: { analysisId }, global: { plugins: [pinia] } })
  await vi.waitFor(() => expect(systemQueue).toHaveBeenCalled())
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('QueuePosition', () => {
  it('reads "N for <guest>" for a queued analysis, per its guest line', async () => {
    const wrapper = await mountFor(
      { running: [], queued_count: 2, queued: [{ id: 9, filename: 'a.exe', guest: 'lab3', position: 2 }] },
      9,
    )
    expect(wrapper.text()).toBe('2 for lab3')
  })

  it('shows only the position for a queued analysis that runs in no guest', async () => {
    const wrapper = await mountFor({ running: [], queued_count: 1, queued: [{ id: 9, filename: 'a.pcap', guest: null, position: 1 }] }, 9)
    expect(wrapper.text()).toBe('position 1')
  })

  it('renders nothing for an analysis that is not queued', async () => {
    const wrapper = await mountFor({ running: [], queued_count: 0, queued: [] }, 9)
    expect(wrapper.text()).toBe('')
  })
})
