import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import SelfTestVerdict from '@/components/guest/SelfTestVerdict.vue'
import type { SelfTestVerdict as Verdict } from '@/services/guest-build'

const PASSED: Verdict = {
  message: 'all checks passed',
  analysisId: 41,
  signals: [
    { id: 'events.process', label: 'PROCESS EVENTS', ok: true, message: '3 processes recorded' },
    { id: 'events.file', label: 'FILE EVENTS', ok: true, message: '12 file events recorded' },
  ],
  proofs: [{ id: 'defender', label: 'DEFENDER', ok: true, message: 'EICAR was kept; Defender is off' }],
  giveaways: [],
}
const FAILED: Verdict = {
  message: 'no registry event was recorded; the guest gives itself away',
  analysisId: 70,
  signals: [
    { id: 'events.process', label: 'PROCESS EVENTS', ok: true, message: '3 processes recorded' },
    { id: 'events.registry', label: 'REGISTRY EVENTS', ok: false, message: 'no registry event was recorded' },
  ],
  proofs: [{ id: 'defender', label: 'DEFENDER', ok: false, message: 'Defender removed the EICAR file' }],
  giveaways: ['account "Analyst"', 'folder C:\\tartarus'],
}

async function mountVerdict(props: { passed: boolean; guest?: string; message?: string; verdict?: Verdict }) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:p(.*)*', component: { template: '<div />' } }] })
  await router.push('/')
  return mount(SelfTestVerdict, { global: { plugins: [Quasar, router] }, props: { guest: 'lab4', message: props.verdict?.message ?? 'x', ...props } })
}

describe('SelfTestVerdict when the self-test passed', () => {
  it('says the guest is ready, with the self-test’s message', async () => {
    const wrapper = await mountVerdict({ passed: true, verdict: PASSED })
    expect(wrapper.text()).toContain('GUEST READY')
    expect(wrapper.text()).toContain('all checks passed')
    expect(wrapper.find('[data-verdict="passed"]').exists()).toBe(true)
  })

  it('lists each signal with a tick and its own message', async () => {
    const wrapper = await mountVerdict({ passed: true, verdict: PASSED })
    const rows = wrapper.findAll('[data-verdict="signal"]')
    expect(rows.map((row) => row.text())).toEqual([expect.stringContaining('PROCESS EVENTS'), expect.stringContaining('FILE EVENTS')])
    expect(rows.every((row) => row.attributes('data-ok') === 'true')).toBe(true)
    expect(rows[0]!.text()).toContain('3 processes recorded')
  })

  it('shows the Defender proof line and the link to the self-test analysis', async () => {
    const wrapper = await mountVerdict({ passed: true, verdict: PASSED })
    expect(wrapper.find('[data-verdict="proof"]').text()).toContain('EICAR was kept; Defender is off')
    expect(wrapper.find('a[href="/analyses/41"]').exists()).toBe(true)
  })

  it('opens the guest page', async () => {
    const wrapper = await mountVerdict({ passed: true, verdict: PASSED })
    const open = wrapper.findAll('a').find((link) => link.text().includes('[OPEN GUEST VM]'))!
    expect(open.attributes('href')).toBe('/guest')
  })

  it('still says the guest is ready, plainly, when the self-test left no details', async () => {
    const wrapper = await mountVerdict({ passed: true, message: 'The guest was built.' })
    expect(wrapper.text()).toContain('GUEST READY')
    expect(wrapper.find('[data-verdict="signal"]').exists()).toBe(false)
  })
})

describe('SelfTestVerdict when the self-test failed', () => {
  it('says so in red with the message and that the guest is failed and unregistered', async () => {
    const wrapper = await mountVerdict({ passed: false, verdict: FAILED })
    expect(wrapper.find('[data-verdict="failed"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('SELF-TEST FAILED')
    expect(wrapper.text()).toContain('no registry event was recorded; the guest gives itself away')
    expect(wrapper.text()).toContain('lab4')
    expect(wrapper.text()).toContain('unregistered')
  })

  it('highlights the failing signals and proofs and leaves the passing ones alone', async () => {
    const wrapper = await mountVerdict({ passed: false, verdict: FAILED })
    expect(wrapper.findAll('[data-verdict="signal"]').map((row) => row.attributes('data-ok'))).toEqual(['true', 'false'])
    expect(wrapper.find('[data-verdict="proof"]').attributes('data-ok')).toBe('false')
  })

  it('lists the giveaways', async () => {
    const wrapper = await mountVerdict({ passed: false, verdict: FAILED })
    expect(wrapper.findAll('[data-verdict="giveaway"]').map((row) => row.text())).toEqual(['account "Analyst"', 'folder C:\\tartarus'])
  })

  it('names the reason even when no signals were stored', async () => {
    const wrapper = await mountVerdict({ passed: false, message: 'The self-test of lab4 failed: the control service went away' })
    expect(wrapper.text()).toContain('the control service went away')
    expect(wrapper.find('[data-verdict="giveaway"]').exists()).toBe(false)
  })

  it('opens the guest page', async () => {
    const wrapper = await mountVerdict({ passed: false, verdict: FAILED })
    expect(wrapper.findAll('a').some((link) => link.text().includes('[OPEN GUEST VM]') && link.attributes('href') === '/guest')).toBe(true)
  })
})
