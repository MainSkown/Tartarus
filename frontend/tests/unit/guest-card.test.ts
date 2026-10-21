import { mount } from '@vue/test-utils'
import { Notify, Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import GuestCard from '@/components/guest/GuestCard.vue'
import type { CheckState } from '@/composables/use-guest-list'
import { buildFixture, guestFixture, WINDOWS_PROFILE } from './guest-fixtures'

type Props = InstanceType<typeof GuestCard>['$props']

async function mountCard(props: Partial<Props> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:p(.*)*', component: { template: '<div />' } }],
  })
  await router.push('/')
  const wrapper = mount(GuestCard, {
    global: { plugins: [Quasar, router] },
    props: { guest: guestFixture(), profile: WINDOWS_PROFILE, ...props },
  })
  return { wrapper, router }
}

const button = (wrapper: Awaited<ReturnType<typeof mountCard>>['wrapper'], label: string) =>
  wrapper.findAll('button, a').find((element) => element.text().includes(label))

beforeEach(() => {
  Notify.create = vi.fn()
})

describe('GuestCard fields', () => {
  it('shows everything about a ready guest', async () => {
    const { wrapper } = await mountCard()
    const text = wrapper.text()
    expect(wrapper.find('.guest-card__name').text()).toBe('lab1')
    expect(text).toContain('READY')
    expect(text).toContain('Windows Pro')
    expect(text).toContain('DEFENDER ON')
    expect(text).toContain('BUILD')
    expect(text).toContain('4 vCPUs · 8 GB RAM · 80 GB disk')
    expect(text).toContain('192.168.150.10')
    expect(text).toContain('Marta')
    expect(text).toContain('DESKTOP-4K7QX2A')
    expect(text).toContain('clean')
    expect(text).toContain('2026-10-16 09:30:00 UTC')
    expect(text).toContain('all signals present')
  })

  it('marks the default guest only when it is the default', async () => {
    expect((await mountCard({ isDefault: true })).wrapper.text()).toContain('DEFAULT')
    expect((await mountCard({ isDefault: false })).wrapper.text()).not.toContain('DEFAULT')
  })

  it('says what a clone was cloned from', async () => {
    const { wrapper } = await mountCard({ guest: guestFixture({ kind: 'clone', cloned_from: 'lab1' }) })
    expect(wrapper.text()).toContain('CLONE OF lab1')
  })

  it('names the Defender state with a label, not only a colour', async () => {
    const { wrapper } = await mountCard({ guest: guestFixture({ badges: ['DEFENDER OFF', 'DECOYS'] }) })
    expect(wrapper.text()).toContain('DEFENDER OFF')
    expect(wrapper.text()).toContain('DECOYS')
  })

  it('skips the rows a guest has no value for', async () => {
    const { wrapper } = await mountCard({ guest: guestFixture({ ip: null, snapshot: null, identity: null, resources: null, selftest: null }) })
    expect(wrapper.text()).not.toContain('SNAPSHOT')
    expect(wrapper.text()).not.toContain('PASSWORD')
    expect(wrapper.text()).not.toContain('SELF-TEST')
  })
})

describe('GuestCard password', () => {
  it('hides the password until revealed, then hides it again', async () => {
    const { wrapper } = await mountCard()
    expect(wrapper.text()).not.toContain('q7Zp-Lm2x-Rv9')

    await button(wrapper, 'REVEAL')!.trigger('click')
    expect(wrapper.text()).toContain('q7Zp-Lm2x-Rv9')
    expect(button(wrapper, 'REVEAL')).toBeUndefined()

    await button(wrapper, 'HIDE')!.trigger('click')
    expect(wrapper.text()).not.toContain('q7Zp-Lm2x-Rv9')
  })

  it('does not reveal the password to someone reading the page as text through the copy button', async () => {
    const { wrapper } = await mountCard()
    expect(wrapper.find('[aria-label="Copy password"]').exists()).toBe(true)
    expect(wrapper.html()).not.toContain('q7Zp-Lm2x-Rv9')
  })

  it('reveals a long password without widening the card', async () => {
    const { wrapper } = await mountCard({ guest: guestFixture({ identity: { account: 'a', machine: 'b', password: 'x'.repeat(64) } }) })
    await button(wrapper, 'REVEAL')!.trigger('click')
    expect(wrapper.find('.guest-card__secret').text()).toContain('x'.repeat(64))
  })
})

describe('GuestCard self-test', () => {
  it('links to the analysis that ran it', async () => {
    const { wrapper } = await mountCard()
    expect(wrapper.find('a[href="/analyses/41"]').exists()).toBe(true)
  })

  it('has no link when the test never submitted its sample', async () => {
    const { wrapper } = await mountCard({ guest: guestFixture({ selftest: { message: 'the sample did not run', analysis_id: null } }) })
    expect(wrapper.text()).toContain('the sample did not run')
    expect(wrapper.find('a[href^="/analyses/"]').exists()).toBe(false)
  })
})

describe('GuestCard giveaway note', () => {
  const adopted = guestFixture({ adopted: true, kind: 'build', giveaways: ['account Analyst', 'folder C:\\tartarus'] })

  it('lists the giveaways of an adopted guest and advises a rebuild or clone', async () => {
    const { wrapper } = await mountCard({ guest: adopted })
    const note = wrapper.find('.guest-card__giveaways')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('account Analyst')
    expect(note.text()).toContain('folder C:\\tartarus')
    expect(note.text()).toContain('Rebuild or clone for a clean guest')
  })

  it('has no note for a guest that was built by the wizard', async () => {
    expect((await mountCard()).wrapper.find('.guest-card__giveaways').exists()).toBe(false)
  })

  it('has no note for an adopted guest with nothing to report', async () => {
    const { wrapper } = await mountCard({ guest: guestFixture({ adopted: true, giveaways: [] }) })
    expect(wrapper.find('.guest-card__giveaways').exists()).toBe(false)
  })
})

describe('GuestCard actions', () => {
  it('offers a ready guest RUN CHECKS, CLONE and DELETE, and no build link', async () => {
    const { wrapper } = await mountCard()
    expect(button(wrapper, 'RUN CHECKS')).toBeDefined()
    expect(button(wrapper, 'CLONE')).toBeDefined()
    expect(button(wrapper, 'DELETE')).toBeDefined()
    expect(button(wrapper, 'VIEW BUILD')).toBeUndefined()
  })

  it('asks for the checks, and for the delete', async () => {
    const { wrapper } = await mountCard()
    await button(wrapper, 'RUN CHECKS')!.trigger('click')
    await button(wrapper, 'DELETE')!.trigger('click')
    expect(wrapper.emitted('runChecks')).toHaveLength(1)
    expect(wrapper.emitted('remove')).toHaveLength(1)
  })

  it('links CLONE to the clone form of that guest', async () => {
    const { wrapper } = await mountCard()
    expect(button(wrapper, 'CLONE')!.attributes('href')).toBe('/guest/clone/lab1')
  })

  it('shows progress and a link to the build for a building guest, with no checks and no delete', async () => {
    const guest = guestFixture({ name: 'lab4', state: 'building', build_id: 'b-lab4', identity: null, selftest: null })
    const { wrapper } = await mountCard({ guest, build: buildFixture() })
    expect(wrapper.text()).toContain('42%')
    expect(wrapper.text()).toContain('Provisioning the guest')
    expect(button(wrapper, 'VIEW BUILD')!.attributes('href')).toBe('/guest/builds/b-lab4')
    expect(button(wrapper, 'RUN CHECKS')).toBeUndefined()
    expect(button(wrapper, 'DELETE')).toBeUndefined()
    expect(button(wrapper, 'CLONE')).toBeUndefined()
  })

  it('shows a building guest whose progress is not known yet', async () => {
    const guest = guestFixture({ name: 'lab4', state: 'testing', build_id: 'b-lab4' })
    const { wrapper } = await mountCard({ guest })
    expect(wrapper.text()).toContain('TESTING')
    expect(button(wrapper, 'VIEW BUILD')).toBeDefined()
  })

  it('shows the error of a failed guest, which can be deleted and whose build can be seen', async () => {
    const guest = guestFixture({ name: 'lab5', state: 'failed', error: 'the install step stopped: no disk', build_id: 'b5' })
    const { wrapper } = await mountCard({ guest })
    expect(wrapper.find('.guest-card__error').text()).toContain('the install step stopped: no disk')
    expect(button(wrapper, 'DELETE')).toBeDefined()
    expect(button(wrapper, 'VIEW BUILD')).toBeDefined()
    expect(button(wrapper, 'RUN CHECKS')).toBeUndefined()
  })

  it('shows the error of a broken guest, which can only be deleted', async () => {
    const guest = { name: 'lab6', state: 'broken', error: 'guest.json could not be read' } as const
    const { wrapper } = await mountCard({ guest, profile: undefined })
    expect(wrapper.find('.guest-card__error').text()).toContain('guest.json could not be read')
    expect(button(wrapper, 'DELETE')).toBeDefined()
    expect(button(wrapper, 'CLONE')).toBeUndefined()
  })

  it('disables DELETE and shows it busy while the delete runs', async () => {
    const { wrapper } = await mountCard({ deleting: true })
    expect(button(wrapper, 'DELETE')!.attributes('disabled')).toBeDefined()
  })

  it('shows why a delete was refused', async () => {
    const { wrapper } = await mountCard({ deleteError: 'An analysis is running' })
    expect(wrapper.find('.guest-card__refusal').text()).toContain('An analysis is running')
  })
})

describe('GuestCard checks', () => {
  it('shows nothing before the checks have run', async () => {
    expect((await mountCard()).wrapper.find('.guest-checks').exists()).toBe(false)
  })

  it('shows a busy state and disables the button while the checks run', async () => {
    const check: CheckState = { busy: true }
    const { wrapper } = await mountCard({ check })
    expect(wrapper.find('.guest-checks').text()).toContain('this takes up to 2 minutes')
    expect(button(wrapper, 'RUN CHECKS')!.attributes('disabled')).toBeDefined()
  })

  it('lists every check with its message, and says which failed', async () => {
    const check: CheckState = {
      busy: false,
      result: {
        name: 'lab1',
        checks: [
          { id: 'agent', ok: true, message: 'agent answers on 8000' },
          { id: 'internet', ok: false, message: 'the guest reached the internet' },
        ],
      },
    }
    const { wrapper } = await mountCard({ check })
    const rows = wrapper.findAll('.guest-checks__row')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.text()).toContain('agent answers on 8000')
    expect(rows[1]!.text()).toContain('the guest reached the internet')
    expect(rows[1]!.classes()).toContain('guest-checks__row--failed')
    expect(wrapper.find('.guest-checks').text()).toContain('1 of 2 checks passed')
  })

  it('shows the reason the checks were refused', async () => {
    const { wrapper } = await mountCard({ check: { busy: false, error: 'An analysis is running' } })
    expect(wrapper.find('.guest-checks').text()).toContain('An analysis is running')
  })
})

describe('GuestCard re-run self-test', () => {
  const failedAfterBuild = guestFixture({ state: 'failed', selftest: { message: 'no DNS answer', analysis_id: 41 }, build_id: 'b2' })
  const label = 'RE-RUN SELF-TEST'

  it('offers the button on a failed guest that has a self-test verdict', async () => {
    const { wrapper } = await mountCard({ guest: failedAfterBuild })
    expect(button(wrapper, label)).toBeDefined()
  })

  it.each([
    ['a ready guest', guestFixture()],
    ['a failed guest the self-test never reached', guestFixture({ state: 'failed', selftest: null, build_id: 'b2' })],
    ['a testing guest', guestFixture({ state: 'testing', selftest: null, build_id: 'b2' })],
  ])('does not offer it on %s', async (_what, guest) => {
    const { wrapper } = await mountCard({ guest })
    expect(button(wrapper, label)).toBeUndefined()
  })

  it('asks for the self-test to be run again when pressed', async () => {
    const { wrapper } = await mountCard({ guest: failedAfterBuild })
    await button(wrapper, label)!.trigger('click')
    expect(wrapper.emitted('retestSelfTest')).toHaveLength(1)
  })

  it('shows it busy and does not take a second press while the request runs', async () => {
    const { wrapper } = await mountCard({ guest: failedAfterBuild, retesting: true })
    const pressed = button(wrapper, label)!
    expect(pressed.attributes('disabled')).toBeDefined()
    expect(pressed.find('.q-spinner').exists()).toBe(true)
  })

  it('shows the refusal the control service gave, as an alert on the card', async () => {
    const { wrapper } = await mountCard({ guest: failedAfterBuild, retestError: 'lab1 never finished building' })
    expect(wrapper.find('.guest-card__refusal[role="alert"]').text()).toContain('lab1 never finished building')
  })

  it('shows a delete refusal and a retest refusal together', async () => {
    const { wrapper } = await mountCard({ guest: failedAfterBuild, deleteError: 'being cloned', retestError: 'an analysis runs' })
    const refusals = wrapper.findAll('.guest-card__refusal').map((refusal) => refusal.text())
    expect(refusals).toEqual([expect.stringContaining('being cloned'), expect.stringContaining('an analysis runs')])
  })
})
