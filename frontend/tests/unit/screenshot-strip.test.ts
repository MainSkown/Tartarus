import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ARTIFACTS_VIEW } from './detections-fixtures'

vi.mock('@/api', () => ({ viewsArtifacts: vi.fn() }))

const { viewsArtifacts } = await import('@/api')
const ScreenshotStrip = (await import('@/components/ScreenshotStrip.vue')).default

const artifactsMock = vi.mocked(viewsArtifacts)
const succeeded = (data: unknown) => ({ data, error: undefined }) as never
const mounted: ReturnType<typeof mount>[] = []

async function mountStrip() {
  const wrapper = mount(ScreenshotStrip, { attachTo: document.body, global: { plugins: [Quasar] }, props: { analysisId: 45 } })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  artifactsMock.mockResolvedValue(succeeded(ARTIFACTS_VIEW))
})

afterEach(() => {
  mounted.splice(0).forEach((wrapper) => wrapper.unmount())
})

describe('ScreenshotStrip', () => {
  it('asks for the artifacts of the analysis', async () => {
    await mountStrip()
    expect(artifactsMock).toHaveBeenCalledWith(expect.objectContaining({ path: { analysis_id: 45 } }))
  })

  it('shows one lazy thumbnail per screenshot, loaded from the screenshot endpoint', async () => {
    const images = (await mountStrip()).findAll('.screenshot-strip__thumb img')
    expect(images.map((image) => image.attributes('src'))).toEqual([
      '/api/analyses/45/artifacts/screenshots/1',
      '/api/analyses/45/artifacts/screenshots/2',
      '/api/analyses/45/artifacts/screenshots/3',
    ])
    expect(images.every((image) => image.attributes('loading') === 'lazy')).toBe(true)
    expect(images.map((image) => image.attributes('alt'))).toEqual([
      'Screenshot 1 of 3',
      'Screenshot 2 of 3',
      'Screenshot 3 of 3',
    ])
  })

  it('says how many screenshots there are', async () => {
    expect((await mountStrip()).text()).toContain('3 screenshots')
  })

  it('opens the lightbox on the clicked thumbnail', async () => {
    const wrapper = await mountStrip()
    expect(document.body.querySelector('.screenshot-lightbox__image')).toBeNull()

    await wrapper.findAll('.screenshot-strip__thumb')[1]!.trigger('click')
    await flushPromises()

    expect(document.body.querySelector('.screenshot-lightbox__image')!.getAttribute('alt')).toBe('Screenshot 2 of 3')
  })

  it('says so when the analysis has no screenshots', async () => {
    artifactsMock.mockResolvedValue(succeeded({ ...ARTIFACTS_VIEW, screenshots: [] }))
    const wrapper = await mountStrip()
    expect(wrapper.text()).toContain('> no screenshots were captured')
    expect(wrapper.find('.screenshot-strip__thumb').exists()).toBe(false)
  })

  it('says it could not load, with a retry, when the request fails', async () => {
    artifactsMock.mockResolvedValueOnce({ data: undefined, error: { error: { message: 'boom' } } } as never)
    const wrapper = await mountStrip()
    expect(wrapper.text()).toContain('failed to load: boom')

    await wrapper.find('.retry-btn').trigger('click')
    await flushPromises()

    expect(wrapper.findAll('.screenshot-strip__thumb')).toHaveLength(3)
  })

  it('shows the loader while the request is out', () => {
    artifactsMock.mockReturnValue(new Promise(() => undefined) as never)
    const wrapper = mount(ScreenshotStrip, { global: { plugins: [Quasar] }, props: { analysisId: 45 } })
    expect(wrapper.find('.loader').exists()).toBe(true)
  })
})
