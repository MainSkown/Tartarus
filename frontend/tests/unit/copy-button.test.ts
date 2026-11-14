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

  describe('with text that has to be fetched first', () => {
    function mountLazy(text: () => Promise<string | undefined>, extra: Record<string, unknown> = {}) {
      return mount(CopyButton, { global: { plugins: [Quasar] }, props: { text, what: 'password', ...extra } })
    }

    it('fetches the text when pressed, and copies it', async () => {
      const writeText = vi.fn().mockResolvedValue(undefined)
      stubClipboard(writeText)
      const text = vi.fn().mockResolvedValue('fetched-value')
      const wrapper = mountLazy(text)
      expect(text).not.toHaveBeenCalled()
      await wrapper.trigger('click')
      await flushPromises()
      expect(text).toHaveBeenCalledTimes(1)
      expect(writeText).toHaveBeenCalledWith('fetched-value')
      expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-success', message: 'password copied' }))
    })

    it('shows a spinner and takes no second press while the text is being fetched', async () => {
      stubClipboard(vi.fn().mockResolvedValue(undefined))
      let settle: (value: string) => void = () => undefined
      const text = vi.fn().mockReturnValue(new Promise<string>((resolve) => (settle = resolve)))
      const wrapper = mountLazy(text)
      await wrapper.trigger('click')
      expect(wrapper.attributes('disabled')).toBeDefined()
      expect(wrapper.attributes('aria-busy')).toBe('true')
      expect(wrapper.find('.q-spinner').exists()).toBe(true)
      await wrapper.trigger('click')
      expect(text).toHaveBeenCalledTimes(1)
      settle('late')
      await flushPromises()
      expect(wrapper.attributes('disabled')).toBeUndefined()
      expect(wrapper.find('.q-spinner').exists()).toBe(false)
    })

    it('copies nothing and says nothing when there is no text: the caller has reported why', async () => {
      const writeText = vi.fn()
      stubClipboard(writeText)
      const wrapper = mountLazy(vi.fn().mockResolvedValue(undefined))
      await wrapper.trigger('click')
      await flushPromises()
      expect(writeText).not.toHaveBeenCalled()
      expect(Notify.create).not.toHaveBeenCalled()
      expect(wrapper.attributes('disabled')).toBeUndefined()
    })

    it('stays disabled while its parent says it is busy', () => {
      stubClipboard(vi.fn())
      expect(mountLazy(vi.fn(), { disabled: true }).attributes('disabled')).toBeDefined()
    })
  })
})
