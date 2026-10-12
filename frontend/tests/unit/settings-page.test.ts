import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { Notify, Quasar, QInput } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { settingsRead, settingsReplace, type ErrorEnvelope, type SettingsBody } from '@/api'
import SettingsPage from '@/pages/SettingsPage.vue'

vi.mock('@/api', () => ({
  settingsRead: vi.fn(),
  settingsReplace: vi.fn(),
}))

type ReadResult = Awaited<ReturnType<typeof settingsRead>>
type ReplaceResult = Awaited<ReturnType<typeof settingsReplace>>

const SAVED: SettingsBody = {
  default_route: 'inetsim',
  default_timeout: 180,
  default_interactive: true,
  disk_warn_gb: 50,
  disk_block_gb: 20,
}

function succeeded(data: SettingsBody) {
  return { data, error: undefined } as unknown as ReadResult & ReplaceResult
}

function failedValidation(fields: { location: string[]; message: string }[]) {
  const error: ErrorEnvelope = {
    error: {
      code: 'validation_error',
      message: 'Request validation failed',
      details: {
        fields: fields.map((field) => ({ ...field, type: 'value_error' })),
      },
    },
  }
  return { data: undefined, error } as unknown as ReadResult & ReplaceResult
}

async function mountLoaded(settings: SettingsBody = SAVED) {
  vi.mocked(settingsRead).mockResolvedValue(succeeded(settings))
  const wrapper = mount(SettingsPage, { global: { plugins: [Quasar] } })
  await flushPromises()
  return wrapper
}

// happy-dom does not turn a click on a submit button into a form submit, so the form is
// submitted directly: the same event the browser fires for the [SAVE] button.
async function submitForm(wrapper: VueWrapper) {
  await wrapper.find('form').trigger('submit')
}

function numberInput(wrapper: VueWrapper, label: string) {
  const input = wrapper
    .findAllComponents(QInput)
    .find((component) => component.props('label') === label)
  if (!input) throw new Error(`no q-input labelled ${label}`)
  return input
}

// Quasar only attaches Notify.create once its plugin is installed (see api.test.ts), so the
// property is assigned directly rather than spied on.
beforeEach(() => {
  vi.clearAllMocks()
  Notify.create = vi.fn()
})

describe('SettingsPage', () => {
  it('shows a loader until the read resolves, then the loaded values', async () => {
    let resolveRead: (result: ReadResult) => void = () => undefined
    const pendingRead = new Promise<ReadResult>((resolve) => {
      resolveRead = resolve
    })
    vi.mocked(settingsRead).mockReturnValue(pendingRead as ReturnType<typeof settingsRead>)
    const wrapper = mount(SettingsPage, { global: { plugins: [Quasar] } })
    expect(wrapper.find('.loader').exists()).toBe(true)
    expect(wrapper.find('.save-btn').exists()).toBe(false)

    resolveRead(succeeded(SAVED))
    await flushPromises()

    expect(wrapper.find('.loader').exists()).toBe(false)
    expect(numberInput(wrapper, 'DEFAULT TIMEOUT').find('input').element.value).toBe('180')
    expect(numberInput(wrapper, 'DISK WARN (GB)').find('input').element.value).toBe('50')
    expect(numberInput(wrapper, 'DISK BLOCK (GB)').find('input').element.value).toBe('20')
    expect(wrapper.find<HTMLInputElement>('input[value="inetsim"]').element.checked).toBe(true)
    expect(wrapper.find<HTMLInputElement>('.checkbox-input').element.checked).toBe(true)
  })

  it('offers a retry when the read fails', async () => {
    vi.mocked(settingsRead).mockResolvedValueOnce({ data: undefined, error: {} } as unknown as ReadResult)
    const wrapper = mount(SettingsPage, { global: { plugins: [Quasar] } })
    await flushPromises()
    expect(wrapper.text()).toContain('> failed to load settings')
    expect(wrapper.find('.save-btn').exists()).toBe(false)

    vi.mocked(settingsRead).mockResolvedValueOnce(succeeded(SAVED))
    await wrapper.find('.retry-btn').trigger('click')
    await flushPromises()
    expect(settingsRead).toHaveBeenCalledTimes(2)
    expect(wrapper.find('.save-btn').exists()).toBe(true)
  })

  it('saves the current form values and toasts success with the persisted body', async () => {
    const wrapper = await mountLoaded()
    await numberInput(wrapper, 'DEFAULT TIMEOUT').find('input').setValue('300')
    vi.mocked(settingsReplace).mockResolvedValue(
      succeeded({ ...SAVED, default_timeout: 600 }) as unknown as ReplaceResult,
    )

    await submitForm(wrapper)
    await flushPromises()

    expect(settingsReplace).toHaveBeenCalledWith({
      body: { ...SAVED, default_timeout: 300 },
    })
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-success' }))
    expect(numberInput(wrapper, 'DEFAULT TIMEOUT').find('input').element.value).toBe('600')
  })

  it('shows a 422 field message inline on the specific inputs it names', async () => {
    const wrapper = await mountLoaded()
    vi.mocked(settingsReplace).mockResolvedValue(
      failedValidation([
        { location: ['body', 'default_route'], message: 'Input should be a valid route' },
        { location: ['body', 'disk_warn_gb'], message: 'must be greater than disk_block_gb' },
      ]),
    )

    await submitForm(wrapper)
    await flushPromises()

    const warn = numberInput(wrapper, 'DISK WARN (GB)')
    expect(warn.props('error')).toBe(true)
    expect(warn.props('errorMessage')).toBe('must be greater than disk_block_gb')
    expect(numberInput(wrapper, 'DEFAULT TIMEOUT').props('error')).toBe(false)
    expect(numberInput(wrapper, 'DISK BLOCK (GB)').props('error')).toBe(false)
    expect(wrapper.find('.field-error').text()).toBe('Input should be a valid route')
    expect(Notify.create).not.toHaveBeenCalled()
  })

  it('clears a stale field error once the next save succeeds', async () => {
    const wrapper = await mountLoaded()
    vi.mocked(settingsReplace).mockResolvedValueOnce(
      failedValidation([{ location: ['body', 'disk_warn_gb'], message: 'must be greater than disk_block_gb' }]),
    )
    await submitForm(wrapper)
    await flushPromises()
    expect(numberInput(wrapper, 'DISK WARN (GB)').props('error')).toBe(true)

    await numberInput(wrapper, 'DISK WARN (GB)').find('input').setValue('60')
    vi.mocked(settingsReplace).mockResolvedValueOnce(succeeded({ ...SAVED, disk_warn_gb: 60 }) as unknown as ReplaceResult)
    await submitForm(wrapper)
    await flushPromises()

    expect(numberInput(wrapper, 'DISK WARN (GB)').props('error')).toBe(false)
    expect(numberInput(wrapper, 'DISK WARN (GB)').props('errorMessage')).toBeUndefined()
  })

  it('replaces a stale field error with the new save error, dropping the old one', async () => {
    const wrapper = await mountLoaded()
    vi.mocked(settingsReplace).mockResolvedValueOnce(
      failedValidation([{ location: ['body', 'disk_warn_gb'], message: 'must be greater than disk_block_gb' }]),
    )
    await submitForm(wrapper)
    await flushPromises()

    vi.mocked(settingsReplace).mockResolvedValueOnce(
      failedValidation([{ location: ['body', 'default_timeout'], message: 'Input should be at least 60' }]),
    )
    await submitForm(wrapper)
    await flushPromises()

    expect(numberInput(wrapper, 'DISK WARN (GB)').props('error')).toBe(false)
    expect(numberInput(wrapper, 'DEFAULT TIMEOUT').props('errorMessage')).toBe('Input should be at least 60')
  })
})
