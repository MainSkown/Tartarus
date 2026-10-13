import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar, QBtn, QInput } from 'quasar'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisRead, ErrorEnvelope, SystemHealth } from '@/api'

const READY: SystemHealth = {
  postgres: { status: 'ok', message: null },
  opensearch: { status: 'ok', message: null },
  cape: { status: 'ok', message: null },
  guest: { status: 'ok', message: null },
}

const CREATED = { id: 7, filename: 'invoice.exe', status: 'queued' } as AnalysisRead

vi.mock('@/api', () => ({
  analysesCreate: vi.fn(),
  analysesList: vi.fn(),
  settingsRead: vi.fn(),
  systemHealth: vi.fn().mockResolvedValue({ data: undefined }),
}))

vi.mock('@/services/ws', () => ({
  createSystemHealthClient: () => ({
    state: { value: 'open' },
    lastMessage: { value: undefined },
    subscribe: () => () => undefined,
    connect: () => undefined,
    disconnect: () => undefined,
  }),
}))

const { analysesCreate, settingsRead } = await import('@/api')
const SubmitDialog = (await import('@/components/SubmitDialog.vue')).default
const { useSystemStore } = await import('@/stores/system')

type CreateResult = Awaited<ReturnType<typeof analysesCreate>>
type SettingsResult = Awaited<ReturnType<typeof settingsRead>>

// QDialog teleports its content out of the wrapper; a pass-through keeps it queryable.
const hideDialog = vi.fn()
const QDialogStub = defineComponent({
  setup(_, { slots }) {
    return () => h('div', slots.default?.())
  },
  methods: { show: () => undefined, hide: () => hideDialog() },
})

const SAMPLE = new File(['MZ-binary'], 'invoice.exe')

async function mountDialog({ guest = 'ok' as 'ok' | 'down' } = {}) {
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: { render: () => null } },
      { path: '/analyses/:id/:tab?', name: 'analysis-workspace', component: { render: () => null } },
    ],
  })
  await router.push('/')
  useSystemStore().health = {
    ...READY,
    guest: guest === 'ok' ? READY.guest : { status: 'down', message: 'guest VM is stopped' },
  }
  const wrapper = mount(SubmitDialog, { global: { plugins: [Quasar, router], stubs: { QDialog: QDialogStub } } })
  await flushPromises()
  return { wrapper, router }
}

async function chooseFile(wrapper: VueWrapper, file: File = SAMPLE) {
  const input = wrapper.find('.file-input')
  Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
  await input.trigger('change')
  await flushPromises()
}

function textInput(wrapper: VueWrapper, label: string) {
  const input = wrapper.findAllComponents(QInput).find((component) => component.props('label') === label)
  if (!input) throw new Error(`no q-input labelled ${label}`)
  return input
}

async function submit(wrapper: VueWrapper) {
  await wrapper.find('form').trigger('submit')
  await flushPromises()
}

function failedValidation(fields: { location: string[]; message: string }[]) {
  const error: ErrorEnvelope = {
    error: {
      code: 'validation_error',
      message: 'Request validation failed',
      details: { fields: fields.map((field) => ({ ...field, type: 'value_error' })) },
    },
  }
  return { data: undefined, error } as unknown as CreateResult
}

function created() {
  return { data: CREATED, error: undefined } as unknown as CreateResult
}

function sentOptions() {
  const [{ body }] = vi.mocked(analysesCreate).mock.calls[0]!
  return JSON.parse(body.options as string) as Record<string, unknown>
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(settingsRead).mockResolvedValue({ data: undefined, error: {} } as unknown as SettingsResult)
})

describe('SubmitDialog', () => {
  describe('choosing a file', () => {
    it('shows the name and size of the chosen file and its SHA-256', async () => {
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper, new File(['abc'], 'invoice.exe'))

      expect(wrapper.find('.file-name').text()).toBe('invoice.exe')
      expect(wrapper.find('.file-size').text()).toBe('3 B')
      await vi.waitFor(() =>
        expect(wrapper.find('.file-hash').text()).toContain(
          'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
        ),
      )
    })

    it('accepts a file dropped on the drop zone', async () => {
      const { wrapper } = await mountDialog()

      await wrapper.find('.drop-zone').trigger('drop', { dataTransfer: { files: [SAMPLE] } })
      await flushPromises()

      expect(wrapper.find('.file-name').text()).toBe('invoice.exe')
    })

    it('refuses more than one dropped file and keeps the earlier choice', async () => {
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper)

      await wrapper
        .find('.drop-zone')
        .trigger('drop', { dataTransfer: { files: [new File(['a'], 'a.exe'), new File(['b'], 'b.exe')] } })
      await flushPromises()

      expect(wrapper.find('.drop-error').text()).toContain('one file')
      expect(wrapper.find('.file-name').text()).toBe('invoice.exe')
    })

    it('marks the drop zone while a file is dragged over it', async () => {
      const { wrapper } = await mountDialog()
      await wrapper.find('.drop-zone').trigger('dragover')
      expect(wrapper.find('.drop-zone').classes()).toContain('drop-zone--over')

      await wrapper.find('.drop-zone').trigger('dragleave')
      expect(wrapper.find('.drop-zone').classes()).not.toContain('drop-zone--over')
    })

    it('puts the whole file name in a tooltip target so a long name can truncate', async () => {
      const longName = `${'very-long-name-'.repeat(12)}.exe`
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper, new File(['x'], longName))

      expect(wrapper.find('.file-name').text()).toBe(longName)
      expect(wrapper.find('.file-name').attributes('title')).toBe(longName)
    })
  })

  describe('the submit button', () => {
    it('is disabled with the reason until a file is chosen', async () => {
      const { wrapper } = await mountDialog()
      expect(wrapper.find('.submit-btn').attributes('disabled')).toBeDefined()
      expect(wrapper.find('.submit-reason').text()).toBe('Choose a sample to analyse')

      await chooseFile(wrapper)

      expect(wrapper.find('.submit-btn').attributes('disabled')).toBeUndefined()
      expect(wrapper.find('.submit-reason').exists()).toBe(false)
    })

    it('is disabled with the guest message while the guest is not ready, even with a file', async () => {
      const { wrapper } = await mountDialog({ guest: 'down' })
      await chooseFile(wrapper)

      expect(wrapper.find('.submit-btn').attributes('disabled')).toBeDefined()
      expect(wrapper.find('.submit-reason').text()).toBe('guest VM is stopped')
    })

    it('does not call the backend when the form is submitted without a file', async () => {
      const { wrapper } = await mountDialog()
      await submit(wrapper)
      expect(analysesCreate).not.toHaveBeenCalled()
    })
  })

  describe('route', () => {
    it('offers the built routes as a radio group defaulting to inetsim', async () => {
      const { wrapper } = await mountDialog()
      const radios = wrapper.findAll<HTMLInputElement>('input[name="route"]')

      expect(radios.map((radio) => radio.element.value)).toEqual(['inetsim', 'none', 'drop', 'internet'])
      expect(wrapper.find<HTMLInputElement>('#route-inetsim').element.checked).toBe(true)
    })

    it('starts from the default route and timeout in Settings', async () => {
      vi.mocked(settingsRead).mockResolvedValue({
        data: { default_route: 'drop', default_timeout: 300 },
        error: undefined,
      } as unknown as SettingsResult)
      const { wrapper } = await mountDialog()

      expect(wrapper.find<HTMLInputElement>('#route-drop').element.checked).toBe(true)
      expect(textInput(wrapper, 'TIMEOUT').find('input').element.value).toBe('300')
    })

    it('warns inline, and only, while internet is chosen', async () => {
      const { wrapper } = await mountDialog()
      expect(wrapper.find('.internet-warning').exists()).toBe(false)

      await wrapper.find('#route-internet').setValue(true)

      expect(wrapper.find('.internet-warning').text()).toContain('real internet')
    })
  })

  describe('timeout', () => {
    it('defaults to 180 seconds', async () => {
      const { wrapper } = await mountDialog()
      expect(textInput(wrapper, 'TIMEOUT').find('input').element.value).toBe('180')
    })

    it.each(['59', '1201', '', '90.5'])('rejects %j inline and disables the submit button', async (value) => {
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper)

      await textInput(wrapper, 'TIMEOUT').find('input').setValue(value)

      expect(textInput(wrapper, 'TIMEOUT').props('error')).toBe(true)
      expect(textInput(wrapper, 'TIMEOUT').props('errorMessage')).toBe('Timeout must be a whole number from 60 to 1200 seconds')
      expect(wrapper.find('.submit-btn').attributes('disabled')).toBeDefined()
    })

    it.each(['60', '1200'])('accepts the bound %s', async (value) => {
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper)

      await textInput(wrapper, 'TIMEOUT').find('input').setValue(value)

      expect(textInput(wrapper, 'TIMEOUT').props('error')).toBe(false)
      expect(wrapper.find('.submit-btn').attributes('disabled')).toBeUndefined()
    })
  })

  describe('submitting', () => {
    it('sends the file with the chosen route, timeout and package', async () => {
      vi.mocked(analysesCreate).mockResolvedValue(created())
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper)
      await wrapper.find('#route-drop').setValue(true)
      await textInput(wrapper, 'TIMEOUT').find('input').setValue('300')
      await textInput(wrapper, 'PACKAGE').find('input').setValue('doc')

      await submit(wrapper)

      expect(analysesCreate).toHaveBeenCalledTimes(1)
      expect(vi.mocked(analysesCreate).mock.calls[0]![0].body.file).toBe(SAMPLE)
      expect(sentOptions()).toEqual({ route: 'drop', timeout: 300, package: 'doc' })
    })

    it('leaves the package out when it is blank so the backend picks auto', async () => {
      vi.mocked(analysesCreate).mockResolvedValue(created())
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper)
      await textInput(wrapper, 'PACKAGE').find('input').setValue('   ')

      await submit(wrapper)

      expect(sentOptions()).toEqual({ route: 'inetsim', timeout: 180 })
    })

    it('shows the in-flight state and blocks a second submit while uploading', async () => {
      let finishUpload: (result: CreateResult) => void = () => undefined
      vi.mocked(analysesCreate).mockReturnValue(
        new Promise<CreateResult>((resolve) => {
          finishUpload = resolve
        }) as ReturnType<typeof analysesCreate>,
      )
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper)

      await submit(wrapper)
      await submit(wrapper)

      expect(wrapper.findAllComponents(QBtn).find((btn) => btn.classes('submit-btn'))?.props('loading')).toBe(true)
      expect(wrapper.find('.cancel-btn').attributes('disabled')).toBeDefined()
      expect(analysesCreate).toHaveBeenCalledTimes(1)

      finishUpload(created())
      await flushPromises()
    })

    it('closes the dialog and opens the new analysis on success', async () => {
      vi.mocked(analysesCreate).mockResolvedValue(created())
      const { wrapper, router } = await mountDialog()
      await chooseFile(wrapper)

      await submit(wrapper)

      expect(wrapper.emitted('ok')).toHaveLength(1)
      expect(router.currentRoute.value.name).toBe('analysis-workspace')
      expect(router.currentRoute.value.params.id).toBe('7')
    })

    it('shows a 422 message under the field it names and keeps the dialog open', async () => {
      vi.mocked(analysesCreate).mockResolvedValue(
        failedValidation([
          { location: ['body', 'options', 'timeout'], message: 'Input should be at least 60' },
          { location: ['body', 'options', 'package'], message: 'unknown package' },
          { location: ['body', 'file'], message: 'The uploaded file is empty' },
        ]),
      )
      const { wrapper, router } = await mountDialog()
      await chooseFile(wrapper)

      await submit(wrapper)

      expect(textInput(wrapper, 'TIMEOUT').props('errorMessage')).toBe('Input should be at least 60')
      expect(textInput(wrapper, 'PACKAGE').props('errorMessage')).toBe('unknown package')
      expect(wrapper.find('.file-error').text()).toBe('The uploaded file is empty')
      expect(wrapper.find('.error-banner').exists()).toBe(false)
      expect(wrapper.emitted('ok')).toBeUndefined()
      expect(router.currentRoute.value.name).toBe('dashboard')
    })

    it('shows the message in a banner when the failure names no field, and clears it on the next try', async () => {
      const refused = {
        data: undefined,
        error: { error: { code: 'conflict', message: 'The analysis guest is not ready (down)' } },
      } as unknown as CreateResult
      vi.mocked(analysesCreate).mockResolvedValueOnce(refused).mockResolvedValueOnce(created())
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper)

      await submit(wrapper)
      expect(wrapper.find('.error-banner').text()).toContain('The analysis guest is not ready (down)')
      expect(wrapper.find('.submit-btn').attributes('disabled')).toBeUndefined()

      await submit(wrapper)
      expect(wrapper.find('.error-banner').exists()).toBe(false)
    })

    it('puts a 422 for an unknown field in the banner so nothing is swallowed', async () => {
      vi.mocked(analysesCreate).mockResolvedValue(
        failedValidation([{ location: ['body', 'options', 'machine'], message: 'extra not permitted' }]),
      )
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper)

      await submit(wrapper)

      expect(wrapper.find('.error-banner').text()).toContain('extra not permitted')
    })
  })

  it('closes without submitting on cancel', async () => {
    const { wrapper } = await mountDialog()

    await wrapper.find('.cancel-btn').trigger('click')

    expect(analysesCreate).not.toHaveBeenCalled()
    expect(hideDialog).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('ok')).toBeUndefined()
  })
})
