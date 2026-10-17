import { flushPromises, mount } from '@vue/test-utils'
import { Notify, Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CopyButton from '@/components/CopyButton.vue'

function mountButton() {
  return mount(CopyButton, { global: { plugins: [Quasar] }, props: { text: 'abc123', what: 'SHA-256' } })
}

function stubClipboard(writeText: ReturnType<typeof vi.fn> | undefined): void {
  Object.defineProperty(navigator, 'clipboard', { value: writeText && { writeText }, configurable: true })
}

beforeEach(() => {
  Notify.create = vi.fn()
})

describe('CopyButton', () => {
  it('shows a label next to the icon when it is given one, and still copies', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubClipboard(writeText)
    const wrapper = mount(CopyButton, { global: { plugins: [Quasar] }, props: { text: 'log', what: 'build log', label: '[COPY LOG]' } })
    expect(wrapper.text()).toContain('[COPY LOG]')
    await wrapper.trigger('click')
    expect(writeText).toHaveBeenCalledWith('log')
  })

  it('is labelled for what it copies', () => {
    stubClipboard(vi.fn())
    expect(mountButton().attributes('aria-label')).toBe('Copy SHA-256')
  })

  it('copies the text and confirms with a toast', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubClipboard(writeText)
    await mountButton().trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith('abc123')
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-success', message: 'SHA-256 copied' }))
  })

  it('says so when the browser refuses the copy', async () => {
    stubClipboard(vi.fn().mockRejectedValue(new Error('denied')))
    await mountButton().trigger('click')
    await flushPromises()
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-error' }))
  })

  it('says so when there is no clipboard to fall back on either', async () => {
    stubClipboard(undefined)
    document.execCommand = vi.fn().mockReturnValue(false)
    await mountButton().trigger('click')
    await flushPromises()
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-error' }))
  })
})
