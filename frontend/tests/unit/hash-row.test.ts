import { flushPromises, mount } from '@vue/test-utils'
import { Notify, Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import HashRow from '@/components/HashRow.vue'

const HASH = '9f2c1d0e8b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2a1b'
const writeText = vi.fn().mockResolvedValue(undefined)

function mountRow(props: { label?: string; hash: string | null; absentHint?: string }) {
  return mount(HashRow, { global: { plugins: [Quasar] }, props: { label: 'FILE SHA-256', ...props } })
}

beforeEach(() => {
  vi.clearAllMocks()
  Notify.create = vi.fn()
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
})

describe('HashRow', () => {
  it('shows the label and the full hash, with the hash as its own title', () => {
    const wrapper = mountRow({ hash: HASH })
    expect(wrapper.find('.hash-row__label').text()).toBe('FILE SHA-256')
    expect(wrapper.find('.hash-row__hash').text()).toBe(HASH)
    expect(wrapper.find('.hash-row__hash').attributes('title')).toBe(HASH)
  })

  it('copies the hash and names the label in the confirmation', async () => {
    const wrapper = mountRow({ hash: HASH })
    await wrapper.find('.copy-button').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith(HASH)
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-success', message: expect.stringContaining('FILE SHA-256') }))
  })

  it('says not recorded, with the hint as title and nothing to copy, when there is no hash', () => {
    const wrapper = mountRow({ hash: null, absentHint: 'appears when the run is finished' })
    const absent = wrapper.find('.hash-row__absent')
    expect(absent.text()).toBe('NOT RECORDED')
    expect(absent.attributes('title')).toBe('appears when the run is finished')
    expect(wrapper.find('.hash-row__hash').exists()).toBe(false)
    expect(wrapper.find('.copy-button').exists()).toBe(false)
  })
})
