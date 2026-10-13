import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { useFullscreen } from '@/composables/use-fullscreen'

function setFullscreenElement(element: Element | null): void {
  Object.defineProperty(document, 'fullscreenElement', { value: element, configurable: true })
  document.dispatchEvent(new Event('fullscreenchange'))
}

function mountProbe(request: () => Promise<void>) {
  let api!: ReturnType<typeof useFullscreen>
  const Probe = defineComponent({
    setup() {
      const target = ref<HTMLElement>()
      api = useFullscreen(target)
      return () => h('div', { ref: target })
    },
  })
  const wrapper = mount(Probe, { attachTo: document.body })
  wrapper.element.requestFullscreen = vi.fn(request)
  document.exitFullscreen = vi.fn(() => {
    setFullscreenElement(null)
    return Promise.resolve()
  })
  return { wrapper, api }
}

afterEach(() => {
  setFullscreenElement(null)
  document.body.innerHTML = ''
})

describe('useFullscreen', () => {
  it('asks the browser to make the target fullscreen and follows the change', async () => {
    const { wrapper, api } = mountProbe(() => {
      setFullscreenElement(wrapper.element)
      return Promise.resolve()
    })
    await api.toggle()
    expect(wrapper.element.requestFullscreen).toHaveBeenCalledOnce()
    expect(api.active.value).toBe(true)
  })

  it('leaves fullscreen when toggled while active', async () => {
    const { wrapper, api } = mountProbe(() => Promise.resolve())
    setFullscreenElement(wrapper.element)
    expect(api.active.value).toBe(true)
    await api.toggle()
    expect(document.exitFullscreen).toHaveBeenCalledOnce()
    expect(api.active.value).toBe(false)
  })

  it('says why when the browser refuses', async () => {
    const { api } = mountProbe(() => Promise.reject(new TypeError('Permissions check failed')))
    await api.toggle()
    await flushPromises()
    expect(api.active.value).toBe(false)
    expect(api.error.value).toBe('fullscreen was refused: Permissions check failed')
  })

  it('clears the refusal on the next try', async () => {
    let refuse = true
    const { wrapper, api } = mountProbe(() => (refuse ? Promise.reject(new Error('no')) : Promise.resolve()))
    await api.toggle()
    refuse = false
    await api.toggle()
    expect(api.error.value).toBeUndefined()
    expect(wrapper.element.requestFullscreen).toHaveBeenCalledTimes(2)
  })

  it('stops listening when the component goes away', () => {
    const remove = vi.spyOn(document, 'removeEventListener')
    const { wrapper } = mountProbe(() => Promise.resolve())
    wrapper.unmount()
    expect(remove).toHaveBeenCalledWith('fullscreenchange', expect.any(Function))
  })

  it('reads a browser without the API as a refusal', async () => {
    const { wrapper, api } = mountProbe(() => Promise.resolve())
    ;(wrapper.element as { requestFullscreen?: unknown }).requestFullscreen = undefined
    await api.toggle()
    expect(api.error.value).toBe('fullscreen was refused: this browser has no fullscreen support')
  })
})
