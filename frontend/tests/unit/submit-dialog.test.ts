import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar, QBtn, QInput, QSelect, QToggle } from 'quasar'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisRead, ErrorEnvelope, Guest, GuestProfile, SystemHealth } from '@/api'
import { BUILT_ROUTES } from '@/services/routes'

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
  guestsList: vi.fn(),
  guestsProfiles: vi.fn(),
  systemHealth: vi.fn().mockResolvedValue({ data: undefined }),
}))

vi.mock('@/services/ws', () => ({
  createSystemClient: () => ({
    state: { value: 'open' },
    lastMessage: { value: undefined },
    subscribe: () => () => undefined,
    connect: () => undefined,
    disconnect: () => undefined,
  }),
}))

const { analysesCreate, guestsList, guestsProfiles, settingsRead } = await import('@/api')
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

const GUESTS = [
  { name: 'win', state: 'ready', profile: 'windows', badges: ['DEFENDER ON'] },
  { name: 'lab2', state: 'ready', profile: 'windows', badges: ['DEFENDER OFF'] },
  { name: 'lab3', state: 'building', profile: 'windows', badges: [] },
] as Guest[]
const PROFILES = [{ id: 'windows', display_name: 'Windows 11', packages: ['exe', 'dll', 'doc'] }] as GuestProfile[]

const SAMPLE = new File(['MZ-binary'], 'invoice.exe')

async function mountDialog({ guest = 'ok' as 'ok' | 'down' } = {}) {
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: { render: () => null } },
      { path: '/guest', name: 'guest', component: { render: () => null } },
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

function selectLabelled(wrapper: VueWrapper, label: string) {
  const select = wrapper.findAllComponents(QSelect).find((component) => component.props('label') === label)
  if (!select) throw new Error(`no q-select labelled ${label}`)
  return select
}

function listResult(guests: Guest[]) {
  return { data: guests, error: undefined } as unknown as Awaited<ReturnType<typeof guestsList>>
}

function interactiveSwitch(wrapper: VueWrapper) {
  return wrapper.findComponent(QToggle)
}

function storedSettings(settings: Record<string, unknown>) {
  vi.mocked(settingsRead).mockResolvedValue({ data: settings, error: undefined } as unknown as SettingsResult)
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
  vi.mocked(guestsList).mockResolvedValue(listResult(GUESTS))
  vi.mocked(guestsProfiles).mockResolvedValue({ data: PROFILES, error: undefined } as unknown as Awaited<ReturnType<typeof guestsProfiles>>)
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

      expect(radios.map((radio) => radio.element.value)).toEqual(BUILT_ROUTES)
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
      expect(textInput(wrapper, 'TIMEOUT').props('errorMessage')).toBe('Whole seconds, 60 to 1200')
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

  describe('interactive desktop', () => {
    it('is a switch labelled INTERACTIVE DESKTOP, off when settings are unavailable', async () => {
      const { wrapper } = await mountDialog()

      expect(interactiveSwitch(wrapper).props('label')).toBe('INTERACTIVE DESKTOP')
      expect(interactiveSwitch(wrapper).props('modelValue')).toBe(false)
    })

    it.each([true, false])('starts from default_interactive %s in Settings', async (stored) => {
      storedSettings({ default_interactive: stored })
      const { wrapper } = await mountDialog()

      expect(interactiveSwitch(wrapper).props('modelValue')).toBe(stored)
    })

    it('explains that the run lasts the full timeout, in minutes of the timeout field', async () => {
      storedSettings({ default_interactive: true })
      const { wrapper } = await mountDialog()
      expect(wrapper.find('.interactive-note').text()).toBe(
        'Drive the guest yourself. The run lasts the full timeout (3 min) unless you press END RUN on the live page.',
      )

      await textInput(wrapper, 'TIMEOUT').find('input').setValue('1200')
      expect(wrapper.find('.interactive-note').text()).toContain('(20 min)')

      await textInput(wrapper, 'TIMEOUT').find('input').setValue('150')
      expect(wrapper.find('.interactive-note').text()).toContain('(2.5 min)')
    })

    it('drops the minutes while the timeout is not a valid number', async () => {
      storedSettings({ default_interactive: true })
      const { wrapper } = await mountDialog()

      await textInput(wrapper, 'TIMEOUT').find('input').setValue('5')

      expect(wrapper.find('.interactive-note').text()).toBe(
        'Drive the guest yourself. The run lasts the full timeout unless you press END RUN on the live page.',
      )
    })

    it('says how a non-interactive run ends while the switch is off', async () => {
      const { wrapper } = await mountDialog()

      expect(wrapper.find('.interactive-note').text()).toBe(
        'The run ends once the sample has exited, or at the timeout.',
      )
    })

    it('is disabled while submitting', async () => {
      vi.mocked(analysesCreate).mockReturnValue(new Promise(() => undefined) as ReturnType<typeof analysesCreate>)
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper)

      await submit(wrapper)

      expect(interactiveSwitch(wrapper).props('disable')).toBe(true)
    })
  })

  describe('submitting', () => {
    it.each([true, false])('sends interactive %s as a boolean the dialog holds', async (stored) => {
      storedSettings({ default_interactive: stored })
      vi.mocked(analysesCreate).mockResolvedValue(created())
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper)

      await submit(wrapper)

      expect(sentOptions().interactive).toBe(stored)
    })

    it('sends the switch as the analyst left it, not as Settings had it', async () => {
      storedSettings({ default_interactive: false })
      vi.mocked(analysesCreate).mockResolvedValue(created())
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper)
      interactiveSwitch(wrapper).vm.$emit('update:modelValue', true)
      await flushPromises()

      await submit(wrapper)

      expect(sentOptions().interactive).toBe(true)
    })

    it('sends the file with the chosen route, timeout and package', async () => {
      vi.mocked(analysesCreate).mockResolvedValue(created())
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper)
      await wrapper.find('#route-drop').setValue(true)
      await textInput(wrapper, 'TIMEOUT').find('input').setValue('300')
      selectLabelled(wrapper, 'PACKAGE').vm.$emit('update:modelValue', 'doc')
      await flushPromises()

      await submit(wrapper)

      expect(analysesCreate).toHaveBeenCalledTimes(1)
      expect(vi.mocked(analysesCreate).mock.calls[0]![0].body.file).toBe(SAMPLE)
      expect(sentOptions()).toEqual({ route: 'drop', timeout: 300, interactive: false, guest: 'win', package: 'doc' })
    })

    it('leaves the package out while it is auto so the backend picks one', async () => {
      vi.mocked(analysesCreate).mockResolvedValue(created())
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper)

      await submit(wrapper)

      expect(sentOptions()).toEqual({ route: 'inetsim', timeout: 180, interactive: false, guest: 'win' })
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
          { location: ['body', 'options', 'interactive'], message: 'not a valid boolean' },
          { location: ['body', 'file'], message: 'The uploaded file is empty' },
        ]),
      )
      const { wrapper, router } = await mountDialog()
      await chooseFile(wrapper)

      await submit(wrapper)

      expect(textInput(wrapper, 'TIMEOUT').props('errorMessage')).toBe('Input should be at least 60')
      expect(selectLabelled(wrapper, 'PACKAGE').props('errorMessage')).toBe('unknown package')
      expect(wrapper.find('.interactive-error').text()).toBe('not a valid boolean')
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

  describe('guest', () => {
    it('lists every guest, disabling one that is not ready with its state as the reason', async () => {
      const { wrapper } = await mountDialog()
      const options = selectLabelled(wrapper, 'GUEST').props('options') as Record<string, unknown>[]

      expect(options.map((option) => [option.name, option.disabled, option.reason, option.profileName])).toEqual([
        ['win', false, undefined, 'Windows 11'],
        ['lab2', false, undefined, 'Windows 11'],
        ['lab3', true, 'building', 'Windows 11'],
      ])
    })

    it('preselects the first ready guest, or the Settings default when that is ready', async () => {
      expect(selectLabelled((await mountDialog()).wrapper, 'GUEST').props('modelValue')).toBe('win')

      storedSettings({ default_guest: 'lab2' })
      expect(selectLabelled((await mountDialog()).wrapper, 'GUEST').props('modelValue')).toBe('lab2')
    })

    it('loads the guests and the profiles when it opens', async () => {
      await mountDialog()
      expect(guestsList).toHaveBeenCalledTimes(1)
      expect(guestsProfiles).toHaveBeenCalledTimes(1)
    })

    it('sends the guest the analyst picked', async () => {
      vi.mocked(analysesCreate).mockResolvedValue(created())
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper)
      selectLabelled(wrapper, 'GUEST').vm.$emit('update:modelValue', 'lab2')
      await flushPromises()

      await submit(wrapper)

      expect(sentOptions().guest).toBe('lab2')
    })

    it('offers the packages of the chosen guest and goes back to auto when the guest cannot take the chosen one', async () => {
      vi.mocked(guestsList).mockResolvedValue(
        listResult([...GUESTS, { name: 'box', state: 'ready', profile: 'ubuntu', badges: [] } as Guest]),
      )
      vi.mocked(guestsProfiles).mockResolvedValue({
        data: [...PROFILES, { id: 'ubuntu', display_name: 'Ubuntu 24.04', packages: ['bash'] }],
        error: undefined,
      } as unknown as Awaited<ReturnType<typeof guestsProfiles>>)
      const { wrapper } = await mountDialog()
      expect(selectLabelled(wrapper, 'PACKAGE').props('options')).toEqual(['auto', 'exe', 'dll', 'doc'])
      selectLabelled(wrapper, 'PACKAGE').vm.$emit('update:modelValue', 'doc')
      await flushPromises()

      selectLabelled(wrapper, 'GUEST').vm.$emit('update:modelValue', 'box')
      await flushPromises()

      expect(selectLabelled(wrapper, 'PACKAGE').props('options')).toEqual(['auto', 'bash'])
      expect(selectLabelled(wrapper, 'PACKAGE').props('modelValue')).toBe('auto')
    })

    it('shows a 422 on options.guest on the select', async () => {
      vi.mocked(analysesCreate).mockResolvedValue(
        failedValidation([{ location: ['body', 'options', 'guest'], message: 'unknown guest' }]),
      )
      const { wrapper } = await mountDialog()
      await chooseFile(wrapper)

      await submit(wrapper)

      expect(selectLabelled(wrapper, 'GUEST').props('errorMessage')).toBe('unknown guest')
      expect(wrapper.find('.error-banner').exists()).toBe(false)
    })

    describe('when no guest is ready', () => {
      beforeEach(() => {
        vi.mocked(guestsList).mockResolvedValue(listResult([GUESTS[2]!]))
      })

      it('blocks DETONATE with the reason and a link to the Guest page', async () => {
        const { wrapper } = await mountDialog()
        await chooseFile(wrapper)

        expect(wrapper.find('.submit-btn').attributes('disabled')).toBeDefined()
        expect(wrapper.find('.submit-reason').text()).toContain('No guest is ready: lab3 is building')
        expect(wrapper.find('.guest-link').attributes('href')).toBe('/guest')
        expect(wrapper.find('.guest-link').text()).toBe('[OPEN GUEST VM]')
      })

      it('sends nothing, even when the form is submitted', async () => {
        const { wrapper } = await mountDialog()
        await chooseFile(wrapper)
        await submit(wrapper)
        expect(analysesCreate).not.toHaveBeenCalled()
      })
    })

    describe('when the guest list cannot be loaded', () => {
      beforeEach(() => {
        vi.mocked(guestsList).mockResolvedValue({ data: undefined, error: { error: { message: 'down' } } } as unknown as ReturnType<typeof listResult>)
      })

      it('says so and keeps submitting possible, leaving the choice to the backend', async () => {
        vi.mocked(analysesCreate).mockResolvedValue(created())
        const { wrapper } = await mountDialog()
        await chooseFile(wrapper)

        expect(wrapper.find('.guest-unavailable').text()).toContain('guest list')
        expect(wrapper.findAllComponents(QSelect).some((select) => select.props('label') === 'GUEST')).toBe(false)
        expect(wrapper.find('.submit-btn').attributes('disabled')).toBeUndefined()

        await submit(wrapper)
        expect(sentOptions()).toEqual({ route: 'inetsim', timeout: 180, interactive: false })
      })
    })
  })
})
