import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { afterEach, describe, expect, it } from 'vitest'
import ScreenshotLightbox from '@/components/ScreenshotLightbox.vue'

const mounted: ReturnType<typeof mount>[] = []

async function openAt(n: number | null) {
  const wrapper = mount(ScreenshotLightbox, {
    attachTo: document.body,
    global: { plugins: [Quasar] },
    props: { analysisId: 45, count: 3, modelValue: n },
  })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

const image = () => document.body.querySelector<HTMLImageElement>('.screenshot-lightbox__image')
const button = (label: string) => document.body.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)
const press = (key: string, keyCode: number) => {
  window.dispatchEvent(new KeyboardEvent('keydown', { key, keyCode }))
  window.dispatchEvent(new KeyboardEvent('keyup', { key, keyCode }))
}

afterEach(() => {
  mounted.splice(0).forEach((wrapper) => wrapper.unmount())
})

describe('ScreenshotLightbox', () => {
  it('shows nothing while closed', async () => {
    await openAt(null)
    expect(image()).toBeNull()
  })

  it('shows the screenshot full size with alt text that says which one it is', async () => {
    await openAt(2)
    expect(image()!.getAttribute('src')).toBe('/api/analyses/45/artifacts/screenshots/2')
    expect(image()!.getAttribute('alt')).toBe('Screenshot 2 of 3')
  })

  it('goes to the next and the previous screenshot', async () => {
    const wrapper = await openAt(2)
    button('Next screenshot')!.click()
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([3])

    button('Previous screenshot')!.click()
    expect(wrapper.emitted('update:modelValue')?.[1]).toEqual([1])
  })

  it('stops at the first screenshot instead of wrapping', async () => {
    await openAt(1)
    expect(button('Previous screenshot')!.disabled).toBe(true)
    expect(button('Next screenshot')!.disabled).toBe(false)
  })

  it('stops at the last screenshot instead of wrapping', async () => {
    await openAt(3)
    expect(button('Next screenshot')!.disabled).toBe(true)
    expect(button('Previous screenshot')!.disabled).toBe(false)
  })

  it('follows the arrow keys', async () => {
    const wrapper = await openAt(2)
    press('ArrowRight', 39)
    press('ArrowLeft', 37)
    expect(wrapper.emitted('update:modelValue')).toEqual([[3], [1]])
  })

  it('ignores an arrow key at the end of the row', async () => {
    const wrapper = await openAt(3)
    press('ArrowRight', 39)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('does not listen to the arrow keys while closed', async () => {
    const wrapper = await openAt(null)
    press('ArrowRight', 39)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('closes on Escape', async () => {
    const wrapper = await openAt(2)
    press('Escape', 27)
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([null])
  })

  it('closes from the close button', async () => {
    const wrapper = await openAt(2)
    button('Close')!.click()
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([null])
  })

  it('says where it is in the row', async () => {
    await openAt(2)
    expect(document.body.querySelector('.screenshot-lightbox__position')!.textContent).toBe('2 / 3')
  })
})
