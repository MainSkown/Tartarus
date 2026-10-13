import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisStatus } from '@/api'

vi.mock('@/api', () => ({ viewsArtifacts: vi.fn() }))

const { viewsArtifacts } = await import('@/api')
const LiveFinishedPanel = (await import('@/components/LiveFinishedPanel.vue')).default

const artifactsMock = vi.mocked(viewsArtifacts)
const shot = (n: number) => ({ n, name: `${n}.jpg`, size: 100 })
const succeeded = (screenshots: unknown[]) => ({ data: { screenshots }, error: undefined }) as never

async function mountPanel(status: AnalysisStatus = 'done') {
  const wrapper = mount(LiveFinishedPanel, { attachTo: document.body, global: { plugins: [Quasar] }, props: { analysisId: 45, status } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  artifactsMock.mockResolvedValue(succeeded([shot(1), shot(2), shot(3)]))
})

describe('LiveFinishedPanel', () => {
  it('shows the last screenshot of the run, from the screenshot endpoint', async () => {
    const image = (await mountPanel()).find('.live-finished__image img')
    expect(image.attributes('src')).toBe('/api/analyses/45/artifacts/screenshots/3')
    expect(image.attributes('alt')).toBe('Screenshot 3 of 3')
  })

  it('names the last screenshot even when the list is not in order', async () => {
    artifactsMock.mockResolvedValue(succeeded([shot(2), shot(5), shot(1)]))
    const image = (await mountPanel()).find('.live-finished__image img')
    expect(image.attributes('src')).toBe('/api/analyses/45/artifacts/screenshots/5')
  })

  it('says the run is over and how it ended', async () => {
    const wrapper = await mountPanel('done')
    expect(wrapper.find('.pane-heading').text()).toBe('RUN FINISHED')
    expect(wrapper.text()).toContain('DONE')
  })

  it('says there is no screenshot when the run took none', async () => {
    artifactsMock.mockResolvedValue(succeeded([]))
    const wrapper = await mountPanel()
    expect(wrapper.find('.live-finished__image').exists()).toBe(false)
    expect(wrapper.text()).toContain('no screenshot')
  })

  it.each(['failed', 'cancelled', 'report_failed'] as const)('does not look for screenshots of an analysis that %s', async (status) => {
    artifactsMock.mockClear()
    const wrapper = await mountPanel(status)
    expect(artifactsMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('no screenshot')
  })

  it('offers a retry when the screenshots cannot be loaded', async () => {
    artifactsMock.mockResolvedValue({ data: undefined, error: { error: { code: 'x', message: 'index is down', details: {} } } } as never)
    const wrapper = await mountPanel()
    expect(wrapper.text()).toContain('failed to load')
    expect(wrapper.find('.retry-btn').exists()).toBe(true)
  })

  it('asks for the summary when its button is clicked', async () => {
    const wrapper = await mountPanel()
    await wrapper.find('.live-finished__summary').trigger('click')
    expect(wrapper.emitted('open-summary')).toHaveLength(1)
  })

  it('opens the screenshot larger when it is clicked', async () => {
    const wrapper = await mountPanel()
    await wrapper.find('.live-finished__image').trigger('click')
    await flushPromises()
    expect(document.body.querySelector('.screenshot-lightbox__image')?.getAttribute('src')).toBe('/api/analyses/45/artifacts/screenshots/3')
  })
})
