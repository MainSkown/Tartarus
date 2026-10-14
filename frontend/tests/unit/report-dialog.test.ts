import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { defineComponent, h, reactive } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { JobProgress, JobRead, ReportVariant } from '@/api'

vi.mock('@/api', () => ({ exportReport: vi.fn(), jobsRead: vi.fn() }))
vi.mock('@/services/report-job', async (importOriginal: () => Promise<Record<string, unknown>>) => ({
  ...(await importOriginal()),
  downloadReportFile: vi.fn(),
}))

const system = reactive({ connectionState: 'open', onJob: vi.fn() })
let pushJob: (job: JobProgress) => void = () => undefined
vi.mock('@/stores/system', () => ({ useSystemStore: () => system }))

const { exportReport } = await import('@/api')
const { downloadReportFile } = await import('@/services/report-job')
const { useJobsStore } = await import('@/stores/jobs')
const ReportDialog = (await import('@/components/ReportDialog.vue')).default

const hideDialog = vi.fn()
const QDialogStub = defineComponent({
  setup(_, { slots }) {
    return () => h('div', slots.default?.())
  },
  methods: { show: () => undefined, hide: () => hideDialog() },
})

const NOT_FINISHED = 'Analysis 193 is not finished yet'

function jobOf(overrides: Partial<JobProgress> = {}): JobProgress {
  return {
    id: 7,
    type: 'export_report',
    analysis_id: 193,
    status: 'running',
    step: 'Reading the analysis files',
    progress: 0,
    result: null,
    ...overrides,
  }
}

const read = (overrides: Partial<JobProgress> = {}): JobRead => ({
  ...jobOf({ status: 'pending', step: 'Queued', ...overrides }),
  log: '',
  created_at: '2026-10-15T10:00:00Z',
  updated_at: '2026-10-15T10:00:00Z',
})

const DONE = jobOf({
  status: 'done',
  step: 'Saving the file',
  progress: 100,
  result: { filename: 'tartarus-report-193.pdf', media_type: 'application/pdf' },
})

async function mountDialog(initialFormat: ReportVariant = 'pdf', filename = 'loader.dll') {
  const wrapper = mount(ReportDialog, {
    global: { plugins: [Quasar], stubs: { QDialog: QDialogStub } },
    props: { analysisId: 193, filename, initialFormat },
  })
  await flushPromises()
  return wrapper
}

const buttonLabelled = (wrapper: VueWrapper, label: string) => wrapper.findAll('button').find((button) => button.text() === label)
const radio = (wrapper: VueWrapper, value: string) => wrapper.get<HTMLInputElement>(`input[type="radio"][value="${value}"]`)
const checkbox = (wrapper: VueWrapper, key: string) => wrapper.get<HTMLInputElement>(`input[type="checkbox"][name="${key}"]`)

async function generate(wrapper: VueWrapper) {
  await wrapper.get('form').trigger('submit')
  await flushPromises()
}

function accept(overrides: Partial<JobProgress> = {}) {
  vi.mocked(exportReport).mockResolvedValue({ data: read(overrides) } as never)
}

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
  system.onJob.mockReset().mockImplementation((handler: (job: JobProgress) => void) => {
    pushJob = handler
    return () => undefined
  })
  vi.mocked(downloadReportFile).mockResolvedValue(true)
  useJobsStore()
})

describe('ReportDialog form', () => {
  it('preselects the format the menu entry named and includes everything by default', async () => {
    const wrapper = await mountDialog('pdf')
    expect(radio(wrapper, 'pdf').element.checked).toBe(true)
    expect(radio(wrapper, 'html').element.checked).toBe(false)
    for (const key of ['notes', 'screenshots', 'raw_iocs']) expect(checkbox(wrapper, key).element.checked).toBe(true)
  })

  it('explains each include option in one line', async () => {
    const wrapper = await mountDialog()
    const hints = wrapper.findAll('.report-dialog__option-hint').map((hint) => hint.text())
    expect(hints).toHaveLength(3)
    expect(hints[2]).toContain('first five per type')
  })

  it('names the analysis in the title, keeping a long filename reachable', async () => {
    const filename = `${'quarterly-report-'.repeat(8)}.pdf.exe`
    const wrapper = await mountDialog('html', filename)
    expect(wrapper.get('.report-dialog__title').text()).toContain('#193')
    expect(wrapper.get('.report-dialog__filename').attributes('title')).toBe(filename)
  })

  it('sends exactly the chosen format and sections', async () => {
    accept()
    const wrapper = await mountDialog('pdf')

    await radio(wrapper, 'html').setValue(true)
    await checkbox(wrapper, 'notes').setValue(false)
    await checkbox(wrapper, 'raw_iocs').setValue(false)
    await generate(wrapper)

    expect(exportReport).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { analysis_id: 193 },
        body: { format: 'html', include: { notes: false, screenshots: true, raw_iocs: false } },
      }),
    )
  })

  it('sends the defaults untouched', async () => {
    accept()
    const wrapper = await mountDialog('pdf')
    await generate(wrapper)
    expect(exportReport).toHaveBeenCalledWith(
      expect.objectContaining({ body: { format: 'pdf', include: { notes: true, screenshots: true, raw_iocs: true } } }),
    )
  })

  it('cannot be submitted twice while the request is on its way', async () => {
    vi.mocked(exportReport).mockReturnValue(new Promise(() => undefined) as never)
    const wrapper = await mountDialog()
    await generate(wrapper)
    expect(buttonLabelled(wrapper, '[GENERATE]')!.attributes('disabled')).toBeDefined()
    expect(wrapper.find('input[type="radio"]').attributes('disabled')).toBeDefined()
  })

  it('shows a refusal inline and stays on the form', async () => {
    vi.mocked(exportReport).mockResolvedValue({
      error: { error: { code: 'conflict', message: NOT_FINISHED, details: {} } },
    } as never)
    const wrapper = await mountDialog()

    await generate(wrapper)

    expect(wrapper.get('[role="alert"]').text()).toBe(NOT_FINISHED)
    expect(buttonLabelled(wrapper, '[GENERATE]')).toBeDefined()
    expect(wrapper.find('progress').exists()).toBe(false)
  })

  it('clears a refusal when the form is changed', async () => {
    vi.mocked(exportReport).mockResolvedValue({ error: { error: { message: NOT_FINISHED } } } as never)
    const wrapper = await mountDialog()
    await generate(wrapper)

    await checkbox(wrapper, 'notes').setValue(false)

    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('closes with CANCEL', async () => {
    const wrapper = await mountDialog()
    await buttonLabelled(wrapper, 'CANCEL')!.trigger('click')
    expect(hideDialog).toHaveBeenCalled()
  })
})

describe('ReportDialog progress', () => {
  it('shows the bar, the step and the percent of the job from the moment it is accepted', async () => {
    accept()
    const wrapper = await mountDialog()
    await generate(wrapper)

    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.get<HTMLProgressElement>('progress').element.value).toBe(0)
    expect(wrapper.get('.report-dialog__percent').text()).toBe('0%')
    expect(wrapper.get('.report-dialog__step').text()).toBe('Queued')
  })

  it.each([
    [45, 'Rendering the PDF'],
    [99, 'Saving the file'],
  ])('follows the job to %i%% (%s)', async (progress, step) => {
    accept()
    const wrapper = await mountDialog()
    await generate(wrapper)

    pushJob(jobOf({ progress, step }))
    await flushPromises()

    expect(wrapper.get<HTMLProgressElement>('progress').element.value).toBe(progress)
    expect(wrapper.get('.report-dialog__percent').text()).toBe(`${progress}%`)
    expect(wrapper.get('.report-dialog__step').text()).toBe(step)
    expect(wrapper.text()).toContain('keeps building in the background')
  })

  it('closes while the job runs without touching it, and shows the same progress when opened again', async () => {
    accept()
    const first = await mountDialog()
    await generate(first)
    pushJob(jobOf({ progress: 45, step: 'Rendering the PDF' }))
    await flushPromises()

    await buttonLabelled(first, 'CLOSE')!.trigger('click')
    expect(hideDialog).toHaveBeenCalled()
    first.unmount()
    pushJob(jobOf({ progress: 70, step: 'Saving the file' }))

    const second = await mountDialog()
    expect(second.get('.report-dialog__percent').text()).toBe('70%')
    expect(second.find('form').exists()).toBe(false)
    expect(exportReport).toHaveBeenCalledTimes(1)
  })

  it('tells the store a report dialog is open for the analysis only while it is mounted', async () => {
    const jobs = useJobsStore()
    const wrapper = await mountDialog()
    expect(jobs.viewing).toBe(193)
    wrapper.unmount()
    expect(jobs.viewing).toBeUndefined()
  })
})

describe('ReportDialog result', () => {
  it('offers the download of the format that was built once the job is done', async () => {
    accept()
    const wrapper = await mountDialog('pdf')
    await generate(wrapper)

    pushJob(DONE)
    await flushPromises()

    expect(wrapper.text()).toContain('tartarus-report-193.pdf')
    expect(buttonLabelled(wrapper, '[DOWNLOAD PDF]')).toBeDefined()
    await buttonLabelled(wrapper, '[DOWNLOAD PDF]')!.trigger('click')
    expect(downloadReportFile).toHaveBeenCalledWith(DONE)
  })

  it('labels the download after HTML when an HTML report was built', async () => {
    accept()
    const wrapper = await mountDialog('html')
    await generate(wrapper)
    pushJob(jobOf({ status: 'done', progress: 100, result: { filename: 'r.html' } }))
    await flushPromises()
    expect(buttonLabelled(wrapper, '[DOWNLOAD HTML]')).toBeDefined()
  })

  it('shows a finished report when the dialog is opened again and goes back to the form for a new one', async () => {
    accept()
    const first = await mountDialog('pdf')
    await generate(first)
    pushJob(DONE)
    first.unmount()

    const second = await mountDialog('html')
    expect(buttonLabelled(second, '[DOWNLOAD PDF]')).toBeDefined()

    await buttonLabelled(second, '[NEW REPORT]')!.trigger('click')
    expect(radio(second, 'html').element.checked).toBe(true)
    expect(buttonLabelled(second, '[GENERATE]')).toBeDefined()
  })

  it('shows the reason a job failed and retries with the same format and sections', async () => {
    accept()
    const wrapper = await mountDialog('pdf')
    await checkbox(wrapper, 'screenshots').setValue(false)
    await generate(wrapper)

    pushJob(jobOf({ status: 'failed', progress: 85, step: 'Assembling the report', result: { error: 'WeasyPrint ran out of memory' } }))
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('WeasyPrint ran out of memory')

    accept({ id: 8 })
    await buttonLabelled(wrapper, '[RETRY]')!.trigger('click')
    await flushPromises()

    expect(exportReport).toHaveBeenCalledTimes(2)
    expect(vi.mocked(exportReport).mock.calls[1]![0]).toMatchObject({
      body: { format: 'pdf', include: { notes: true, screenshots: false, raw_iocs: true } },
    })
    expect(wrapper.find('progress').exists()).toBe(true)
  })

  it('says an interrupted job lost its backend', async () => {
    accept()
    const wrapper = await mountDialog()
    await generate(wrapper)
    pushJob(jobOf({ status: 'interrupted', progress: 40 }))
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('The backend restarted while the report was being built')
  })

  it('shows a refusal of the retry inline', async () => {
    accept()
    const wrapper = await mountDialog()
    await generate(wrapper)
    pushJob(jobOf({ status: 'failed', result: { error: 'boom' } }))
    await flushPromises()
    vi.mocked(exportReport).mockResolvedValue({ error: { error: { message: NOT_FINISHED } } } as never)

    await buttonLabelled(wrapper, '[RETRY]')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(NOT_FINISHED)
  })
})
