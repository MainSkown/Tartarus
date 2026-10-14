import { flushPromises } from '@vue/test-utils'
import { Notify } from 'quasar'
import { effectScope } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const exportIocs = vi.hoisted(() => vi.fn())
const saveDownload = vi.hoisted(() => vi.fn())
vi.mock('@/api', () => ({ exportIocs }))
vi.mock('@/services/download', () => ({ saveDownload }))

const { IOC_FORMATS, downloadIocs } = await import('@/services/ioc-export')
const { useIocExport } = await import('@/composables/use-ioc-export')

const dismissPreparing = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
  Notify.create = vi.fn(() => dismissPreparing) as unknown as typeof Notify.create
  exportIocs.mockReturnValue(Promise.resolve({ data: new Blob() }))
  saveDownload.mockResolvedValue(true)
})

describe('IOC_FORMATS', () => {
  it('lists STIX 2.1, MISP and CSV', () => {
    expect(IOC_FORMATS.map(({ value, label }) => [value, label])).toEqual([
      ['stix', 'STIX 2.1'],
      ['misp', 'MISP'],
      ['csv', 'CSV'],
    ])
  })
})

describe('downloadIocs', () => {
  it.each([
    ['stix', 'tartarus-193-iocs.stix.json'],
    ['misp', 'tartarus-193-iocs.misp.json'],
    ['csv', 'tartarus-193-iocs.csv'],
  ] as const)('asks for %s as a blob and saves it, naming it %s when the server does not', async (format, fallback) => {
    expect(await downloadIocs(193, format)).toBe(true)

    expect(exportIocs).toHaveBeenCalledWith({ path: { analysis_id: 193 }, query: { format }, parseAs: 'blob' })
    expect(saveDownload).toHaveBeenCalledWith(expect.any(Promise), fallback)
  })

  it('reports a failed download as false', async () => {
    saveDownload.mockResolvedValue(false)
    expect(await downloadIocs(193, 'csv')).toBe(false)
  })
})

describe('useIocExport', () => {
  function start() {
    return effectScope().run(() => useIocExport())!
  }

  it('shows a spinner toast while the file is prepared, then swaps it for a confirmation', async () => {
    let finish: (saved: boolean) => void = () => undefined
    saveDownload.mockReturnValue(new Promise<boolean>((resolve) => (finish = resolve)))
    const iocExport = start()

    const pending = iocExport.download(193, 'misp')
    expect(iocExport.downloading.value).toBe('misp')
    expect(Notify.create).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'tt-info', spinner: true, message: 'Preparing the MISP IOCs…' }),
    )
    expect(dismissPreparing).not.toHaveBeenCalled()

    finish(true)
    await pending
    expect(iocExport.downloading.value).toBeUndefined()
    expect(dismissPreparing).toHaveBeenCalledOnce()
    expect(Notify.create).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: 'tt-success', message: 'MISP IOCs downloaded' }),
    )
  })

  it('takes the spinner toast down and leaves the error toast to the API interceptor on failure', async () => {
    saveDownload.mockResolvedValue(false)
    const iocExport = start()

    await iocExport.download(193, 'stix')
    await flushPromises()

    expect(iocExport.downloading.value).toBeUndefined()
    expect(dismissPreparing).toHaveBeenCalledOnce()
    expect(Notify.create).toHaveBeenCalledTimes(1)
  })

  it('ignores a second request while one is downloading', async () => {
    saveDownload.mockReturnValue(new Promise(() => undefined))
    const iocExport = start()

    void iocExport.download(193, 'csv')
    await iocExport.download(193, 'stix')

    expect(exportIocs).toHaveBeenCalledTimes(1)
  })
})
