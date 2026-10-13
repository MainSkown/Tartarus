import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { useViewportFill } from '@/composables/use-viewport-fill'

const BOTTOM_GAP = 16

function mountFilling(top: number) {
  const Probe = defineComponent({
    setup() {
      const root = ref<HTMLElement>()
      const { height } = useViewportFill(root, BOTTOM_GAP)
      return () => h('div', { ref: root }, String(height.value))
    },
  })
  const wrapper = mount(Probe, { attachTo: document.body })
  const setTop = (value: number) => {
    wrapper.element.getBoundingClientRect = () => ({ top: value }) as DOMRect
  }
  setTop(top)
  return { wrapper, setTop }
}

function resizeWindowTo(innerHeight: number): void {
  window.innerHeight = innerHeight
  window.dispatchEvent(new Event('resize'))
}

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('useViewportFill', () => {
  it('is the viewport height left under the element, minus the bottom gap', async () => {
    window.innerHeight = 720
    const { wrapper } = mountFilling(230)
    resizeWindowTo(720)
    await nextTick()

    expect(wrapper.text()).toBe(String(720 - 230 - BOTTOM_GAP))
  })

  it('follows the window being resized', async () => {
    const { wrapper } = mountFilling(200)

    resizeWindowTo(1000)
    await nextTick()

    expect(wrapper.text()).toBe(String(1000 - 200 - BOTTOM_GAP))
  })

  it('follows the element moving, as when the header above it grows', async () => {
    const { wrapper, setTop } = mountFilling(200)
    resizeWindowTo(800)
    setTop(300)
    resizeWindowTo(800)
    await nextTick()

    expect(wrapper.text()).toBe(String(800 - 300 - BOTTOM_GAP))
  })

  it('stops listening once unmounted', () => {
    const remove = vi.spyOn(window, 'removeEventListener')
    const { wrapper } = mountFilling(200)

    wrapper.unmount()

    expect(remove).toHaveBeenCalledWith('resize', expect.any(Function))
  })
})
