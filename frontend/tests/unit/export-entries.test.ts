import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ExportFormat } from '@/api'
import { analysisFixture, analysisWithStatus } from './analysis-fixtures'

const download = vi.hoisted(() => vi.fn())
const openReportDialog = vi.hoisted(() => vi.fn())
const downloading = vi.hoisted(() => ({ current: undefined as { value: ExportFormat | undefined } | undefined }))

vi.mock('@/composables/use-ioc-export', () => ({
  useIocExport: () => ({ download, downloading: downloading.current }),
}))
vi.mock('@/services/report-dialog', () => ({ openReportDialog }))

const ExportEntries = (await import('@/components/ExportEntries.vue')).default

function mountEntries(analysis = analysisFixture()) {
  return mount(ExportEntries, { global: { plugins: [Quasar] }, props: { analysis } })
}

const entry = (wrapper: ReturnType<typeof mountEntries>, label: string) =>
  wrapper.findAll('.q-item').find((item) => item.text() === label)!

beforeEach(() => {
  vi.clearAllMocks()
  downloading.current = ref<ExportFormat | undefined>(undefined)
})

describe('ExportEntries', () => {
  it('has an IOCS section with STIX 2.1, MISP and CSV and a REPORT section with HTML and PDF', () => {
    const wrapper = mountEntries()
    const headings = wrapper.findAll('.export-entries__heading').map((heading) => heading.text())
    expect(headings).toEqual(['IOCS', 'REPORT'])
    expect(wrapper.findAll('.q-item').map((item) => item.text())).toEqual(['STIX 2.1', 'MISP', 'CSV', 'HTML', 'PDF'])
  })

  it.each([
    ['STIX 2.1', 'stix'],
    ['MISP', 'misp'],
    ['CSV', 'csv'],
  ])('downloads the analysis IOCs as %s at once', async (label, format) => {
    const wrapper = mountEntries(analysisFixture({ id: 193 }))
    await entry(wrapper, label).trigger('click')
    expect(download).toHaveBeenCalledWith(193, format)
    expect(openReportDialog).not.toHaveBeenCalled()
  })

  it.each([
    ['HTML', 'html'],
    ['PDF', 'pdf'],
  ])('opens the report dialog preselected to %s', async (label, format) => {
    const analysis = analysisFixture({ id: 193, filename: 'loader.dll' })
    const wrapper = mountEntries(analysis)
    await entry(wrapper, label).trigger('click')
    expect(openReportDialog).toHaveBeenCalledWith(analysis, format)
    expect(download).not.toHaveBeenCalled()
  })

  it('has no hint and enabled report entries for a finished analysis', () => {
    const wrapper = mountEntries()
    expect(wrapper.find('.export-entries__hint').exists()).toBe(false)
    expect(entry(wrapper, 'PDF').classes()).not.toContain('disabled')
  })

  it.each(['queued', 'running', 'ingesting', 'failed', 'report_failed', 'cancelled'] as const)(
    'disables the report entries of a %s analysis, says why, and keeps the IOC entries',
    async (status) => {
      const wrapper = mountEntries(analysisWithStatus(status))
      expect(wrapper.find('.export-entries__hint').text()).toBe('Reports are built from a finished analysis')
      for (const label of ['HTML', 'PDF']) {
        expect(entry(wrapper, label).attributes('aria-disabled')).toBe('true')
        await entry(wrapper, label).trigger('click')
      }
      expect(openReportDialog).not.toHaveBeenCalled()
      expect(entry(wrapper, 'CSV').attributes('aria-disabled')).not.toBe('true')
    },
  )

  it('disables the IOC entries while one download is under way', () => {
    downloading.current!.value = 'csv'
    const wrapper = mountEntries()
    for (const label of ['STIX 2.1', 'MISP', 'CSV']) expect(entry(wrapper, label).attributes('aria-disabled')).toBe('true')
    expect(entry(wrapper, 'PDF').attributes('aria-disabled')).not.toBe('true')
  })
})
