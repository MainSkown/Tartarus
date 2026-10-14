import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import FilterChips from '@/components/FilterChips.vue'
import { useQueryStateStore } from '@/stores/query-state'

const CMD = { field: 'process.name', value: 'cmd.exe', negate: false }
const DELAY = { field: 'api', value: 'NtDelayExecution', negate: true }

function mountChips(setup: (store: ReturnType<typeof useQueryStateStore>) => void = () => undefined, props = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useQueryStateStore()
  setup(store)
  const wrapper = mount(FilterChips, { props, global: { plugins: [Quasar, pinia] } })
  return { wrapper, store }
}

const chipTexts = (wrapper: ReturnType<typeof mountChips>['wrapper']) =>
  wrapper.findAll('.filter-chip .q-chip__content').map((chip) => chip.text().replace(/\s+/g, ' '))

describe('FilterChips', () => {
  it('renders nothing when there is nothing to show', () => {
    const { wrapper } = mountChips()
    expect(wrapper.findAll('.filter-chip')).toHaveLength(0)
    expect(wrapper.find('.filter-chips').exists()).toBe(false)
  })

  it('shows a chip as field: value', () => {
    const { wrapper } = mountChips((store) => store.addChip(CMD))
    expect(chipTexts(wrapper)).toEqual(['process.name: cmd.exe'])
    expect(wrapper.find('.filter-chip').classes()).not.toContain('is-negated')
  })

  it('shows a negated chip with NOT in front and the negated class', () => {
    const { wrapper } = mountChips((store) => store.addChip(DELAY))
    expect(wrapper.find('.filter-chip__not').text()).toBe('NOT')
    expect(wrapper.find('.filter-chip__label').text()).toBe('api: NtDelayExecution')
    expect(wrapper.find('.filter-chip').classes()).toContain('is-negated')
  })

  it('toggles a chip between is and is not on click', async () => {
    const { wrapper, store } = mountChips((s) => s.addChip(CMD))
    await wrapper.find('.filter-chip').trigger('click')
    expect(store.chips[0]!.negate).toBe(true)
    await wrapper.find('.filter-chip').trigger('click')
    expect(store.chips[0]!.negate).toBe(false)
  })

  it('toggles a chip from the keyboard with Enter and Space', async () => {
    const { wrapper, store } = mountChips((s) => s.addChip(CMD))
    const chip = wrapper.find('.filter-chip')
    expect(chip.attributes('tabindex')).toBe('0')
    await chip.trigger('keyup', { key: 'Enter', keyCode: 13 })
    expect(store.chips[0]!.negate).toBe(true)
    await chip.trigger('keyup', { key: ' ', keyCode: 32 })
    expect(store.chips[0]!.negate).toBe(false)
  })

  it('removes a chip with its × and does not toggle it', async () => {
    const { wrapper, store } = mountChips((s) => {
      s.addChip(CMD)
      s.addChip(DELAY)
    })
    await wrapper.find('[aria-label="Remove filter process.name: cmd.exe"]').trigger('click')
    expect(store.chips).toEqual([DELAY])
  })

  it('titles a chip with what a click does', () => {
    const { wrapper } = mountChips((s) => s.addChip(CMD))
    expect(wrapper.find('.filter-chip').attributes('title')).toBe('process.name: cmd.exe (click to exclude)')
  })

  it('titles a negated chip with its full text and what a click does', () => {
    const { wrapper } = mountChips((s) => s.addChip(DELAY))
    expect(wrapper.find('.filter-chip').attributes('title')).toBe('NOT api: NtDelayExecution (click to include)')
  })

  it('puts the full text of a long value in the title and truncates it on screen', () => {
    const long = 'C:\\Users\\anna\\AppData\\Roaming\\' + 'x'.repeat(200) + '.exe'
    const { wrapper } = mountChips((s) => s.addChip({ field: 'file.path', value: long, negate: false }))
    expect(wrapper.find('.filter-chip').attributes('title')).toContain(long)
    expect(wrapper.find('.filter-chip__label').exists()).toBe(true)
  })

  it('shows a selected process as a pid chip, with its name when it is given', () => {
    const { wrapper } = mountChips((s) => s.setPids([4120, 9708]), { pidNames: { 4120: 'cmd.exe' } })
    expect(chipTexts(wrapper)).toEqual(['pid: 4120 (cmd.exe)', 'pid: 9708'])
  })

  it('removes a pid chip with its ×', async () => {
    const { wrapper, store } = mountChips((s) => s.setPids([4120, 9708]))
    await wrapper.find('[aria-label="Remove filter pid: 4120"]').trigger('click')
    expect(store.pids).toEqual([9708])
  })

  it('does not toggle a pid chip on click: a process cannot be excluded', async () => {
    const { wrapper, store } = mountChips((s) => s.setPids([4120]))
    await wrapper.find('.filter-chip').trigger('click')
    expect(store.pids).toEqual([4120])
    expect(store.chips).toEqual([])
  })

  it('shows the time range to the millisecond', () => {
    const { wrapper } = mountChips((s) => s.setTimeRange({ from: '2026-10-13T12:00:01.250Z', to: '2026-10-13T12:00:04.100Z' }))
    expect(chipTexts(wrapper)).toEqual(['time: 12:00:01.250 – 12:00:04.100'])
  })

  it('shows a time range open at one end', () => {
    const { wrapper } = mountChips((s) => s.setTimeRange({ from: '2026-10-13T12:00:01.250Z', to: null }))
    expect(chipTexts(wrapper)).toEqual(['time: from 12:00:01.250'])
    const { wrapper: other } = mountChips((s) => s.setTimeRange({ from: null, to: '2026-10-13T12:00:04.100Z' }))
    expect(chipTexts(other)).toEqual(['time: until 12:00:04.100'])
  })

  it('removes the time range with its ×', async () => {
    const { wrapper, store } = mountChips((s) => s.setTimeRange({ from: '2026-10-13T12:00:01Z', to: null }))
    await wrapper.find('[aria-label="Remove filter time"]').trigger('click')
    expect(store.timeRange).toBeNull()
  })

  it('lists the chips first, then the pids, then the time range', () => {
    const { wrapper } = mountChips((s) => {
      s.setTimeRange({ from: '2026-10-13T12:00:01Z', to: null })
      s.setPids([1])
      s.addChip(CMD)
    })
    expect(chipTexts(wrapper).map((text) => text.split(':')[0])).toEqual(['process.name', 'pid', 'time'])
  })
})
