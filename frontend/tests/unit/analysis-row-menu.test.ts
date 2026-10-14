import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ANALYSIS_STATUSES } from '@/services/analysis-status'
import { analysisWithStatus } from './analysis-fixtures'

vi.mock('@/composables/use-ioc-export', () => ({ useIocExport: () => ({ download: vi.fn(), downloading: { value: undefined } }) }))
vi.mock('@/services/report-dialog', () => ({ openReportDialog: vi.fn() }))

const AnalysisRowMenu = (await import('@/components/AnalysisRowMenu.vue')).default

afterEach(() => {
  document.body.innerHTML = ''
})

async function openMenu(status: Parameters<typeof analysisWithStatus>[0]) {
  const wrapper = mount(AnalysisRowMenu, {
    attachTo: document.body,
    global: { plugins: [Quasar] },
    props: { analysis: analysisWithStatus(status, { id: 193 }) },
  })
  await wrapper.get('button').trigger('click')
  await flushPromises()
  return wrapper
}

const items = () => [...document.querySelectorAll<HTMLElement>('.row-menu > .q-item')]
const labelOf = (item: HTMLElement) => item.querySelector('.q-item__section--main')?.textContent?.trim()
const entries = () => items().map(labelOf)
const entry = (label: string) => items().find((item) => labelOf(item) === label)!

describe('AnalysisRowMenu', () => {
  it('is a button named after the analysis', () => {
    const wrapper = mount(AnalysisRowMenu, { global: { plugins: [Quasar] }, props: { analysis: analysisWithStatus('done', { id: 193 }) } })
    expect(wrapper.get('button').attributes('aria-label')).toBe('Actions for analysis 193')
  })

  const OFFERED = [
    ['done', ['Open', 'Re-ingest', 'Export', 'Delete']],
    ['report_failed', ['Open', 'Re-ingest', 'Export', 'Delete']],
    ['failed', ['Open', 'Export', 'Delete']],
    ['cancelled', ['Open', 'Export', 'Delete']],
    ['queued', ['Open', 'Export', 'Cancel']],
    ['starting', ['Open', 'Export', 'Cancel']],
    ['running', ['Open', 'Export', 'Cancel']],
    ['processing', ['Open', 'Export', 'Cancel']],
    ['ingesting', ['Open', 'Export', 'Cancel']],
  ] as const

  it('is specified for every status the API defines', () => {
    expect(OFFERED.map(([status]) => status).sort()).toEqual([...ANALYSIS_STATUSES].sort())
  })

  it.each(OFFERED)('offers a %s analysis %j', async (status, expected) => {
    await openMenu(status)
    expect(entries()).toEqual(expected)
  })

  it.each([
    ['Open', 'open'],
    ['Re-ingest', 'reingest'],
    ['Delete', 'remove'],
  ])('emits %s with the analysis id', async (label, event) => {
    const wrapper = await openMenu('done')
    entry(label).click()
    await flushPromises()
    expect(wrapper.emitted(event)).toEqual([[193]])
  })

  it('emits cancel with the analysis id for one that has not finished', async () => {
    const wrapper = await openMenu('running')
    entry('Cancel').click()
    await flushPromises()
    expect(wrapper.emitted('cancel')).toEqual([[193]])
  })

  it('opens the export entries from the Export item', async () => {
    await openMenu('done')
    expect(document.querySelector('.export-entries')).toBeNull()

    entry('Export').click()
    await flushPromises()

    expect(document.querySelector('.export-entries')?.textContent).toContain('STIX 2.1')
  })

  it('does not let a click on the button or an entry reach the row', async () => {
    const rowClick = vi.fn()
    const wrapper = mount(
      { components: { AnalysisRowMenu }, props: ['analysis'], template: '<div @click="rowClick"><AnalysisRowMenu :analysis="analysis" /></div>', methods: { rowClick } },
      { attachTo: document.body, global: { plugins: [Quasar] }, props: { analysis: analysisWithStatus('done', { id: 193 }) } },
    )
    await wrapper.get('button').trigger('click')
    await flushPromises()
    entry('Open').click()
    await flushPromises()
    expect(rowClick).not.toHaveBeenCalled()
  })
})
