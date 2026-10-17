import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Notify, Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { BuildStep, BuildView } from '@/api'
import { failed, succeeded } from './annotation-fixtures'
import { FakeDesktopSocket } from './fake-desktop-socket'
import { resetFakeGuacamole } from './fake-guacamole'
import { buildFixture, guestFixture } from './guest-fixtures'

const api = vi.hoisted(() => ({
  guestsList: vi.fn(),
  guestsReadBuild: vi.fn(),
  guestsActiveBuild: vi.fn(),
  guestsResumeBuild: vi.fn(),
  guestsRestartBuild: vi.fn(),
  guestsContinueBuild: vi.fn(),
  guestsCancelBuild: vi.fn(),
  jobsRead: vi.fn(),
  systemHealth: vi.fn(),
}))
const confirmDestructive = vi.hoisted(() => vi.fn())
const loadGuacamole = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => api)
vi.mock('@/services/confirm', () => ({ confirmDestructive }))
vi.mock('@/services/desktop-guacamole', () => ({ loadGuacamole }))
vi.mock('@/services/ws', () => ({
  resolveWsUrl: (path: string) => `ws://localhost${path}`,
  createSystemClient: () => ({
    state: { value: 'open' },
    subscribe: () => () => undefined,
    connect: () => undefined,
    disconnect: () => undefined,
  }),
}))

const { fakeGuacamole } = await import('./fake-guacamole')
const GuestBuildPage = (await import('@/pages/GuestBuildPage.vue')).default

const step = (name: string, status: BuildStep['status'], overrides: Partial<BuildStep> = {}): BuildStep => ({
  name,
  status,
  weight: 1,
  timeout_s: 60,
  desktop: false,
  progress: 0,
  ...overrides,
})

const STEPS = [step('preflight', 'succeeded'), step('tamper-off', 'running'), step('snapshot', 'pending')]
const running = (overrides: Partial<BuildView> = {}) =>
  buildFixture({ id: 'b1', guest: 'lab4', kind: 'build', status: 'running', percent: 46, message: 'Reconfiguring the copy', steps: STEPS, log: ['preflight: ok', 'guest: agent up'], ...overrides })

const SELFTEST = {
  message: 'every signal was present',
  analysis_id: 41,
  signals: { 'events.process': { ok: true, message: '3 processes recorded' } },
  proofs: { defender: { ok: true, message: 'EICAR was kept' } },
  giveaways: [],
}
const job = (overrides: Record<string, unknown> = {}) =>
  succeeded({ id: 7, type: 'guest_build', analysis_id: null, status: 'running', step: 'Self-test: analysis running', progress: 93, result: null, log: '', created_at: '', updated_at: '', ...overrides })

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/guest/builds/:buildId', component: GuestBuildPage }, { path: '/:p(.*)*', component: { template: '<div />' } }],
  })
  await router.push('/guest/builds/b1')
  await router.isReady()
  const wrapper = mount(GuestBuildPage, { attachTo: document.body, global: { plugins: [Quasar, router] } })
  await flushPromises()
  return wrapper
}

type Wrapper = Awaited<ReturnType<typeof mountPage>>
const buttons = (wrapper: Wrapper) => wrapper.findAll('button, a').map((element) => element.text())
const button = (wrapper: Wrapper, label: string) => wrapper.findAll('button, a').find((element) => element.text().includes(label))!

const mounted: Wrapper[] = []
async function show(buildView: unknown) {
  api.guestsReadBuild.mockResolvedValue(buildView)
  const wrapper = await mountPage()
  mounted.push(wrapper)
  return wrapper
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] })
  setActivePinia(createPinia())
  Notify.create = vi.fn()
  FakeDesktopSocket.reset()
  resetFakeGuacamole()
  loadGuacamole.mockImplementation(() => fakeGuacamole())
  vi.stubGlobal('WebSocket', FakeDesktopSocket)
  api.systemHealth.mockResolvedValue({ data: undefined })
  api.guestsList.mockReset().mockResolvedValue(succeeded([guestFixture({ name: 'lab4', state: 'building' })]))
  api.guestsReadBuild.mockReset()
  api.guestsActiveBuild.mockReset().mockResolvedValue(failed('none', 404))
  api.guestsResumeBuild.mockReset().mockResolvedValue({ data: { job_id: 9, build_id: 'b1', guest: 'lab4' }, error: undefined })
  api.guestsRestartBuild.mockReset().mockResolvedValue({ data: { job_id: 9, build_id: 'b1', guest: 'lab4' }, error: undefined })
  api.guestsContinueBuild.mockReset().mockResolvedValue({ data: { job_id: 9, build_id: 'b1', guest: 'lab4' }, error: undefined })
  api.guestsCancelBuild.mockReset().mockResolvedValue({ data: undefined, error: undefined, response: { status: 202 } })
  api.jobsRead.mockReset().mockResolvedValue(job())
  confirmDestructive.mockReset().mockResolvedValue(true)
})

afterEach(() => {
  mounted.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.unstubAllGlobals()
  vi.useRealTimers()
  document.body.innerHTML = ''
})

describe('GuestBuildPage', () => {
  it('shows a loader until the build has been read', async () => {
    api.guestsReadBuild.mockReturnValue(new Promise(() => undefined))
    const wrapper = await mountPage()
    mounted.push(wrapper)
    expect(wrapper.find('.loader[role="status"]').exists()).toBe(true)
  })

  describe('while the build runs', () => {
    it('headed by the guest name as a link to the Guest VM page, the kind, a RUNNING badge and the progress', async () => {
      const wrapper = await show(succeeded(running()))
      const header = wrapper.find('[data-build="header"]')
      expect(header.find('h1 a').attributes('href')).toBe('/guest')
      expect(header.find('h1').text()).toBe('lab4')
      expect(header.find('[data-build="kind"]').text()).toBe('BUILD')
      expect(header.find('.status-badge').text()).toContain('RUNNING')
      expect(header.find('progress').attributes('value')).toBe('46')
      expect(header.text()).toContain('46%')
      expect(header.text()).toContain('Reconfiguring the copy')
    })

    it('lists the steps with the profile’s names humanised, and the self-test last', async () => {
      const wrapper = await show(succeeded(running()))
      expect(wrapper.findAll('.build-step__name').map((name) => name.text())).toEqual(['PREFLIGHT', 'TAMPER OFF', 'SNAPSHOT', 'SELF TEST'])
    })

    it('shows the log tail', async () => {
      const wrapper = await show(succeeded(running()))
      expect(wrapper.findAll('.build-log__line').map((line) => line.text())).toEqual(['preflight: ok', 'guest: agent up'])
    })

    it('offers nothing but the quiet way back', async () => {
      const wrapper = await show(succeeded(running()))
      expect(buttons(wrapper)).toContain('[BACK TO GUEST VM]')
      for (const label of ['RESUME', 'RESTART', 'CONTINUE', 'OPEN GUEST VM']) expect(buttons(wrapper).join(' ')).not.toContain(label)
    })

    it('calls a clone a CLONE and changes nothing else', async () => {
      const wrapper = await show(succeeded(running({ kind: 'clone' })))
      expect(wrapper.find('[data-build="kind"]').text()).toBe('CLONE')
      expect(wrapper.findAll('.build-step__name')).toHaveLength(4)
    })

    it('has no desktop panel at a step that shows none', async () => {
      const wrapper = await show(succeeded(running({ desktop: false })))
      expect(wrapper.find('[data-desktop="screen"]').exists()).toBe(false)
    })

    it('shows the desktop of this guest at a step that shows one', async () => {
      const wrapper = await show(succeeded(running({ desktop: true })))
      expect(wrapper.find('[data-desktop="screen"]').exists()).toBe(true)
      await vi.waitFor(() => expect(FakeDesktopSocket.instances).toHaveLength(1))
      expect(FakeDesktopSocket.latest.url).toContain('/ws/guests/lab4/desktop')
    })

    it('takes the desktop away when the next step shows none', async () => {
      const wrapper = await show(succeeded(running({ desktop: true })))
      api.guestsReadBuild.mockResolvedValue(succeeded(running({ desktop: false })))
      await vi.advanceTimersByTimeAsync(2_000)
      expect(wrapper.find('[data-desktop="screen"]').exists()).toBe(false)
    })
  })

  describe('when paused', () => {
    const paused = (overrides: Partial<BuildView> = {}) =>
      running({ status: 'paused', desktop: true, pause: { instructions: 'Switch the toggle off, then continue.' }, steps: [step('tamper-off', 'paused')], ...overrides })

    it('shows the instructions prominently with the desktop and a CONTINUE button', async () => {
      const wrapper = await show(succeeded(paused()))
      const note = wrapper.find('.build-notice--amber')
      expect(note.text()).toContain('Switch the toggle off, then continue.')
      expect(note.find('button').text()).toContain('[CONTINUE]')
      expect(wrapper.find('[data-desktop="screen"]').exists()).toBe(true)
      expect(wrapper.find('.status-badge').text()).toContain('PAUSED')
    })

    it('continues the build and shows the button busy until the answer', async () => {
      const wrapper = await show(succeeded(paused()))
      let release: (value: unknown) => void = () => undefined
      api.guestsContinueBuild.mockReturnValue(new Promise((resolve) => (release = resolve)))
      await button(wrapper, '[CONTINUE]').trigger('click')
      expect(api.guestsContinueBuild).toHaveBeenCalledTimes(1)
      expect(wrapper.find('.build-notice--amber button').attributes('disabled')).toBeDefined()
      release({ data: { job_id: 9, build_id: 'b1', guest: 'lab4' }, error: undefined })
      await flushPromises()
      expect(wrapper.find('.build-notice--amber button').attributes('disabled')).toBeUndefined()
    })

    it('shows a refusal inline, under the button', async () => {
      const wrapper = await show(succeeded(paused()))
      api.guestsContinueBuild.mockResolvedValue(failed('An analysis is queued or running', 409))
      await button(wrapper, '[CONTINUE]').trigger('click')
      await flushPromises()
      expect(wrapper.find('.build-notice--amber .build-notice__error').text()).toContain('An analysis is queued or running')
    })

    it('does not name any operating system’s settings of its own', async () => {
      const wrapper = await show(succeeded(paused({ pause: { instructions: 'Do the thing.' } })))
      expect(wrapper.find('.build-notice--amber').text()).not.toMatch(/Windows|Tamper|Defender/i)
    })
  })

  describe('when failed', () => {
    const failedView = () =>
      running({ status: 'failed', message: 'provision exited with code 1: the agent did not answer', steps: [step('preflight', 'succeeded'), step('provision', 'failed', { exit_code: 1 }), step('snapshot', 'pending')] })

    it('highlights the failed step and puts its message in a red block with RESUME and RESTART', async () => {
      const wrapper = await show(succeeded(failedView()))
      const block = wrapper.find('.build-notice--red')
      expect(block.text()).toContain('PROVISION')
      expect(block.text()).toContain('provision exited with code 1: the agent did not answer')
      expect(block.findAll('button').map((element) => element.text())).toEqual(['[RESUME]', '[RESTART]'])
      expect(wrapper.find('.build-step--failed .build-step__name').text()).toBe('PROVISION')
      expect(wrapper.find('.status-badge').text()).toContain('FAILED')
    })

    it('resumes the failed step', async () => {
      const wrapper = await show(succeeded(failedView()))
      await button(wrapper, '[RESUME]').trigger('click')
      expect(api.guestsResumeBuild).toHaveBeenCalledWith(expect.objectContaining({ path: { build_id: 'b1' } }))
      expect(confirmDestructive).not.toHaveBeenCalled()
    })

    it('asks before it restarts and only then restarts', async () => {
      const wrapper = await show(succeeded(failedView()))
      confirmDestructive.mockResolvedValue(false)
      await button(wrapper, '[RESTART]').trigger('click')
      await flushPromises()
      expect(api.guestsRestartBuild).not.toHaveBeenCalled()
      confirmDestructive.mockResolvedValue(true)
      await button(wrapper, '[RESTART]').trigger('click')
      await flushPromises()
      expect(api.guestsRestartBuild).toHaveBeenCalledTimes(1)
    })

    it('keeps following the same build after an action', async () => {
      const wrapper = await show(succeeded(failedView()))
      api.guestsReadBuild.mockResolvedValue(succeeded(running()))
      await button(wrapper, '[RESUME]').trigger('click')
      await flushPromises()
      expect(wrapper.find('.status-badge').text()).toContain('RUNNING')
      expect(wrapper.find('.build-notice--red').exists()).toBe(false)
    })

    it('shows a refusal because an analysis is active inline in the red block', async () => {
      const wrapper = await show(succeeded(failedView()))
      api.guestsResumeBuild.mockResolvedValue(failed('A sample is being analysed; wait until it has finished', 409))
      await button(wrapper, '[RESUME]').trigger('click')
      await flushPromises()
      expect(wrapper.find('.build-notice--red .build-notice__error').text()).toContain('A sample is being analysed')
    })
  })

  describe('after the last step succeeded', () => {
    const succeededView = () => running({ status: 'succeeded', percent: 100, steps: [step('preflight', 'succeeded'), step('snapshot', 'succeeded')] })

    beforeEach(() => api.guestsActiveBuild.mockResolvedValue(succeeded({ build_id: 'b1', guest: 'lab4', job_id: 7 })))

    it('follows the self-test with the job’s percent and step', async () => {
      const wrapper = await show(succeeded(succeededView()))
      expect(wrapper.find('.status-badge').text()).toContain('SELF-TEST')
      expect(wrapper.find('[data-build="percent"]').text()).toBe('93%')
      expect(wrapper.find('[data-build="message"]').text()).toBe('Self-test: analysis running')
      expect(wrapper.find('.build-step[data-status="running"] .build-step__name').text()).toBe('SELF TEST')
    })

    it('shows the green verdict, the signals, the proof, the analysis link and OPEN GUEST VM when it passed', async () => {
      api.jobsRead.mockResolvedValue(job({ status: 'done', progress: 100, result: { guest: 'lab4', state: 'ready', selftest: SELFTEST } }))
      const wrapper = await show(succeeded(succeededView()))
      const verdict = wrapper.find('[data-verdict="passed"]')
      expect(verdict.text()).toContain('GUEST READY')
      expect(verdict.text()).toContain('every signal was present')
      expect(verdict.findAll('[data-verdict="signal"]')).toHaveLength(1)
      expect(verdict.find('[data-verdict="proof"]').text()).toContain('EICAR was kept')
      expect(verdict.find('a[href="/analyses/41"]').exists()).toBe(true)
      expect(button(wrapper, '[OPEN GUEST VM]').attributes('href')).toBe('/guest')
      expect(wrapper.find('.status-badge').text()).toContain('READY')
      expect(buttons(wrapper)).not.toContain('[BACK TO GUEST VM]')
    })

    it('shows the red verdict with the failing signals and the giveaways when it failed', async () => {
      api.jobsRead.mockResolvedValue(job({ status: 'failed', result: { error: 'The self-test of lab4 failed: x' } }))
      api.guestsList.mockResolvedValue(
        succeeded([
          guestFixture({
            name: 'lab4',
            state: 'failed',
            selftest: { ...SELFTEST, message: 'no registry event was recorded', signals: { 'events.registry': { ok: false, message: 'no registry event was recorded' } }, giveaways: ['account "Analyst"'] },
          }),
        ]),
      )
      const wrapper = await show(succeeded(succeededView()))
      const verdict = wrapper.find('[data-verdict="failed"]')
      expect(verdict.text()).toContain('SELF-TEST FAILED')
      expect(verdict.text()).toContain('no registry event was recorded')
      expect(verdict.find('[data-verdict="signal"]').attributes('data-ok')).toBe('false')
      expect(verdict.find('[data-verdict="giveaway"]').text()).toBe('account "Analyst"')
      expect(verdict.text()).toContain('unregistered')
      expect(wrapper.find('.status-badge').text()).toContain('SELF-TEST FAILED')
    })
  })

  describe('when the build cannot be shown', () => {
    it('says the build was not found, with the way back', async () => {
      const wrapper = await show(failed('no such build', 404))
      expect(wrapper.text()).toContain('> build not found')
      expect(wrapper.find('a[href="/guest"]').exists()).toBe(true)
    })

    it('says the control service is not reachable and goes on trying quietly', async () => {
      const wrapper = await show(failed('guest control: unreachable', 502))
      expect(wrapper.text()).toContain('> the guest control service is not reachable')
      expect(wrapper.text()).toContain('trying again')
      api.guestsReadBuild.mockResolvedValue(succeeded(running()))
      await vi.advanceTimersByTimeAsync(2_000)
      expect(wrapper.find('[data-build="header"]').exists()).toBe(true)
      expect(wrapper.text()).not.toContain('trying again')
    })

    it('keeps the build on screen with a note when a later read fails', async () => {
      const wrapper = await show(succeeded(running()))
      api.guestsReadBuild.mockResolvedValue(failed('unreachable', 502))
      await vi.advanceTimersByTimeAsync(2_000)
      expect(wrapper.find('[data-build="header"]').exists()).toBe(true)
      expect(wrapper.find('[data-build="connection-note"]').text()).toContain('trying again')
    })
  })
})

describe('GuestBuildPage cancelling', () => {
  const runningView = () => running({ status: 'running' })
  const pausedView = () => running({ status: 'paused', desktop: true, pause: { instructions: 'Switch the toggle off, then continue.' }, steps: [step('tamper-off', 'paused')] })
  const failedView = () => running({ status: 'failed', message: 'the build was cancelled' })

  beforeEach(() => {
    Notify.create = vi.fn()
  })

  it('offers [CANCEL BUILD] while the build runs', async () => {
    const wrapper = await show(succeeded(runningView()))
    expect(button(wrapper, '[CANCEL BUILD]').exists()).toBe(true)
  })

  it('puts [CANCEL BUILD] in the header, beside the back link, not in a row of its own', async () => {
    const wrapper = await show(succeeded(runningView()))
    const header = wrapper.find('[data-build="header"]')
    expect(header.find('[data-build="cancel"]').text()).toBe('[CANCEL BUILD]')
    expect(header.text()).toContain('[BACK TO GUEST VM]')
    expect(wrapper.find('.build-page__cancel').exists()).toBe(false)
  })

  it('offers [CANCEL BUILD] while the build is paused, beside its CONTINUE', async () => {
    const wrapper = await show(succeeded(pausedView()))
    expect(wrapper.find('[data-build="header"] [data-build="cancel"]').exists()).toBe(true)
    expect(button(wrapper, '[CONTINUE]').exists()).toBe(true)
  })

  it('does not offer it once the build failed or the self-test follows', async () => {
    const failedPage = await show(succeeded(failedView()))
    expect(buttons(failedPage).join(' ')).not.toContain('CANCEL BUILD')
    mounted.splice(0).forEach((wrapper) => wrapper.unmount())
    const succeededPage = await show(succeeded(running({ status: 'succeeded', percent: 100 })))
    expect(buttons(succeededPage).join(' ')).not.toContain('CANCEL BUILD')
  })

  it('cancels once confirmed and then shows the failed build with its RESUME and RESTART', async () => {
    const wrapper = await show(succeeded(runningView()))
    api.guestsReadBuild.mockResolvedValue(succeeded(failedView()))
    await button(wrapper, '[CANCEL BUILD]').trigger('click')
    await flushPromises()
    expect(api.guestsCancelBuild).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.status-badge').text()).toContain('FAILED')
    expect(wrapper.find('.build-notice--red').text()).toContain('BUILD CANCELLED')
    expect(wrapper.find('.build-notice--red').text()).toContain('the build was cancelled')
    expect(buttons(wrapper).join(' ')).toContain('[RESUME]')
  })

  it('shows the button busy as [CANCELLING...] while the request is out', async () => {
    const wrapper = await show(succeeded(runningView()))
    let release: (value: unknown) => void = () => undefined
    api.guestsCancelBuild.mockReturnValue(new Promise((resolve) => (release = resolve)))
    await button(wrapper, '[CANCEL BUILD]').trigger('click')
    await flushPromises()
    expect(button(wrapper, '[CANCELLING...]').attributes('disabled')).toBeDefined()
    release({ data: undefined, error: undefined, response: { status: 202 } })
    await flushPromises()
  })

  it('does not send anything when the analyst declines the confirmation', async () => {
    const wrapper = await show(succeeded(runningView()))
    confirmDestructive.mockResolvedValue(false)
    await button(wrapper, '[CANCEL BUILD]').trigger('click')
    await flushPromises()
    expect(api.guestsCancelBuild).not.toHaveBeenCalled()
  })

  it('shows a 409 refusal as a warning toast', async () => {
    const wrapper = await show(succeeded(runningView()))
    api.guestsCancelBuild.mockResolvedValue(failed('the build is not running', 409))
    await button(wrapper, '[CANCEL BUILD]').trigger('click')
    await flushPromises()
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-warning', message: 'the build is not running' }))
  })
})
