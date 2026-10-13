import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { analysisFixture } from './analysis-fixtures'
import {
  ATTACK_MATRIX,
  DETECTIONS_VIEW,
  EMPTY_ATTACK_MATRIX,
  EMPTY_DETECTIONS_VIEW,
} from './detections-fixtures'

vi.mock('@/api', () => ({ viewsDetections: vi.fn(), viewsAttack: vi.fn() }))

const { viewsAttack, viewsDetections } = await import('@/api')
const DetectionsTab = (await import('@/components/tabs/DetectionsTab.vue')).default

const detectionsMock = vi.mocked(viewsDetections)
const attackMock = vi.mocked(viewsAttack)

const succeeded = (data: unknown) => ({ data, error: undefined }) as never
const failed = (message: string) => ({ data: undefined, error: { error: { code: 'internal_error', message } } }) as never

async function mountTab() {
  const wrapper = mount(DetectionsTab, { global: { plugins: [Quasar] }, props: { analysis: analysisFixture({ id: 45 }) } })
  await flushPromises()
  return wrapper
}

const entryNames = (wrapper: Awaited<ReturnType<typeof mountTab>>) =>
  wrapper.findAll('.detection-entry__name').map((name) => name.text())

beforeEach(() => {
  detectionsMock.mockResolvedValue(succeeded(DETECTIONS_VIEW))
  attackMock.mockResolvedValue(succeeded(ATTACK_MATRIX))
})

describe('DetectionsTab states', () => {
  it('asks for the detections and the matrix of the analysis', async () => {
    await mountTab()
    expect(detectionsMock).toHaveBeenCalledWith(expect.objectContaining({ path: { analysis_id: 45 } }))
    expect(attackMock).toHaveBeenCalledWith(expect.objectContaining({ path: { analysis_id: 45 } }))
  })

  it('keeps its tab marker', async () => {
    expect((await mountTab()).find('[data-tab="detections"]').exists()).toBe(true)
  })

  it('shows the loader until the detections arrive', () => {
    detectionsMock.mockReturnValue(new Promise(() => undefined) as never)
    const wrapper = mount(DetectionsTab, { global: { plugins: [Quasar] }, props: { analysis: analysisFixture() } })
    expect(wrapper.find('.loader').exists()).toBe(true)
  })

  it('shows the error and reloads on retry', async () => {
    detectionsMock.mockResolvedValueOnce(failed('index is down'))
    const wrapper = await mountTab()
    expect(wrapper.text()).toContain('failed to load: index is down')

    await wrapper.find('.retry-btn').trigger('click')
    await flushPromises()

    expect(detectionsMock).toHaveBeenCalledTimes(2)
    expect(entryNames(wrapper).length).toBeGreaterThan(0)
  })

  it('says so when there are no detections', async () => {
    detectionsMock.mockResolvedValue(succeeded(EMPTY_DETECTIONS_VIEW))
    const wrapper = await mountTab()
    expect(wrapper.text()).toContain('> no detections')
    expect(wrapper.find('.detection-entry').exists()).toBe(false)
  })
})

describe('DetectionsTab list', () => {
  it('groups the detections by ruleset, sigma first, only the rulesets that exist', async () => {
    const wrapper = await mountTab()
    expect(wrapper.findAll('.detection-list .pane-heading').map((name) => name.text())).toEqual(['SIGMA', 'CAPE', 'SURICATA'])
  })

  it('shows the severity, the name and the technique ids of an entry', async () => {
    const entry = (await mountTab()).findAll('.detection-entry')[0]!
    expect(entry.find('.severity-badge').text()).toContain('CRITICAL')
    expect(entry.find('.detection-entry__name').text()).toBe('proc_injection_remote_thread')
    expect(entry.find('.detection-entry__techniques').text()).toBe('T1055 T1055.003')
  })

  it('shows how many events triggered the detection when there are any', async () => {
    const entries = (await mountTab()).findAll('.detection-entry')
    const counts = entries.map((entry) => entry.find('.detection-entry__count').exists() && entry.find('.detection-entry__count').text())
    expect(counts).toEqual([false, '2 events', '52 events', false])
  })

  it('selects the first detection by default', async () => {
    const wrapper = await mountTab()
    expect(wrapper.findAll('.detection-entry')[0]!.attributes('aria-current')).toBe('true')
    expect(wrapper.find('.detection-detail__name').text()).toBe('proc_injection_remote_thread')
  })

  it('shows another detection when its entry is clicked', async () => {
    const wrapper = await mountTab()
    await wrapper.findAll('.detection-entry')[2]!.trigger('click')

    expect(wrapper.find('.detection-detail__name').text()).toBe('dllload_suspicious_directory')
    expect(wrapper.find('.detection-detail__description').text()).toBe('A DLL was loaded from a suspicious directory')
    expect(wrapper.findAll('.detection-entry[aria-current="true"]')).toHaveLength(1)
  })
})

describe('DetectionsTab detail', () => {
  it('heads the detail with DESCRIPTION, not a second copy of the ruleset, and states the ruleset as a fact', async () => {
    const wrapper = await mountTab()
    const detail = wrapper.find('.detection-detail')
    expect(detail.find('.pane-heading').text()).toBe('DESCRIPTION')
    expect(detail.find('.detection-detail__ruleset').text()).toBe('SIGMA')
  })


  async function openDetection(name: string) {
    const wrapper = await mountTab()
    const index = entryNames(wrapper).indexOf(name)
    await wrapper.findAll('.detection-entry')[index]!.trigger('click')
    return wrapper
  }

  it('says how many of the triggering events are shown when the list is capped', async () => {
    const wrapper = await openDetection('dllload_suspicious_directory')
    expect(wrapper.findAll('.related-event')).toHaveLength(10)
    expect(wrapper.find('.detection-detail__events-count').text()).toBe('10 of 52 shown')
  })

  it('just counts the triggering events when all are shown', async () => {
    const wrapper = await openDetection('recon_systeminfo')
    expect(wrapper.findAll('.related-event')).toHaveLength(2)
    expect(wrapper.find('.detection-detail__events-count').text()).toBe('2')
  })

  it('shows a triggering event with its lane, summary and process', async () => {
    const wrapper = await openDetection('recon_systeminfo')
    const row = wrapper.find('.related-event')
    expect(row.text()).toContain('API')
    expect(row.text()).toContain('benign.exe called DllLoadNotification #100')
    expect(row.text()).toContain('benign.exe (9708)')
  })

  it('has no events section for a detection with none', async () => {
    const wrapper = await openDetection('ET MALWARE Possible beacon')
    expect(wrapper.find('.related-event').exists()).toBe(false)
    expect(wrapper.text()).toContain('no triggering events recorded')
  })

  it('opens a reference in a new tab without handing over the opener', async () => {
    const wrapper = await mountTab()
    const link = wrapper.find('.detection-detail__references a')
    expect(link.attributes('href')).toBe('https://attack.mitre.org/techniques/T1055/')
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toContain('noopener')
  })

  it('does not turn a reference that is not a web address into a link', async () => {
    const wrapper = await openDetection('ET MALWARE Possible beacon')
    expect(wrapper.findAll('.detection-detail__references a')).toHaveLength(1)
    expect(wrapper.find('.detection-detail__references').text()).toContain('javascript:alert(1)')
  })

  it('shows the matched condition in a code block', async () => {
    const block = (await mountTab()).find('pre.code-block')
    expect(block.text()).toBe('selection:\n  EventID: 8\ncondition: selection')
  })

  it('leaves out the code block and the references when the detection has none', async () => {
    const wrapper = await openDetection('recon_systeminfo')
    expect(wrapper.find('pre').exists()).toBe(false)
    expect(wrapper.find('.detection-detail__references').exists()).toBe(false)
  })

  it('shows the process and the time', async () => {
    const wrapper = await openDetection('recon_systeminfo')
    expect(wrapper.find('.detection-detail__process').text()).toContain('benign.exe (9708)')
    expect(wrapper.find('.detection-detail__time').text()).toBe('2026-10-13 15:39:50 UTC')
  })

  it('says when a detection has no description', async () => {
    const wrapper = await openDetection('ET MALWARE Possible beacon')
    expect(wrapper.find('.detection-detail__description').text()).toBe('no description')
  })
})

describe('DetectionsTab ATT&CK matrix', () => {
  const modeInput = (wrapper: Awaited<ReturnType<typeof mountTab>>, label: string) =>
    wrapper.findAll('.radio-input').find((input) => input.attributes('value') === label)!

  it('starts on the detections and switches to the matrix and back', async () => {
    const wrapper = await mountTab()
    expect(wrapper.find('.attack-matrix').exists()).toBe(false)

    await modeInput(wrapper, 'attack').setValue(true)
    expect(wrapper.find('.attack-matrix').exists()).toBe(true)
    expect(wrapper.find('.detection-entry').exists()).toBe(false)

    await modeInput(wrapper, 'detections').setValue(true)
    expect(wrapper.find('.attack-matrix').exists()).toBe(false)
    expect(wrapper.find('.detection-entry').exists()).toBe(true)
  })

  it('labels the toggle DETECTIONS and ATT&CK', async () => {
    const labels = (await mountTab()).findAll('.radio-label').map((label) => label.text())
    expect(labels).toEqual(['DETECTIONS', 'ATT&CK'])
  })

  it('shows the detections of a clicked technique and selects the first of them', async () => {
    const wrapper = await mountTab()
    await modeInput(wrapper, 'attack').setValue(true)
    await wrapper.findAll('.attack-cell')[1]!.trigger('click')

    expect(wrapper.find('.attack-matrix').exists()).toBe(false)
    expect(entryNames(wrapper)).toEqual(['proc_injection_remote_thread', 'dllload_suspicious_directory'])
    expect(wrapper.find('.detection-detail__name').text()).toBe('proc_injection_remote_thread')
    expect(wrapper.find('.technique-filter').text()).toContain('T1055')
  })

  it('goes back to every detection when the technique filter is cleared', async () => {
    const wrapper = await mountTab()
    await modeInput(wrapper, 'attack').setValue(true)
    await wrapper.findAll('.attack-cell')[1]!.trigger('click')
    await wrapper.find('.technique-filter__clear').trigger('click')

    expect(entryNames(wrapper)).toHaveLength(4)
    expect(wrapper.find('.technique-filter').exists()).toBe(false)
  })

  it('selects the detection of a technique that lists just one', async () => {
    const wrapper = await mountTab()
    await modeInput(wrapper, 'attack').setValue(true)
    await wrapper.findAll('.attack-cell')[0]!.trigger('click')

    expect(entryNames(wrapper)).toEqual(['dllload_suspicious_directory'])
    expect(wrapper.find('.detection-detail__name').text()).toBe('dllload_suspicious_directory')
  })

  it('shows a technique without a name by its id', async () => {
    const wrapper = await mountTab()
    await modeInput(wrapper, 'attack').setValue(true)
    expect(wrapper.findAll('.attack-cell').at(-1)!.text()).toContain('T1999')
  })

  it('says so when no technique was raised', async () => {
    attackMock.mockResolvedValue(succeeded(EMPTY_ATTACK_MATRIX))
    const wrapper = await mountTab()
    await modeInput(wrapper, 'attack').setValue(true)
    expect(wrapper.text()).toContain('> no ATT&CK techniques were raised')
  })

  it('shows its own error with a retry that only reloads the matrix', async () => {
    attackMock.mockResolvedValueOnce(failed('matrix unavailable'))
    const wrapper = await mountTab()
    await modeInput(wrapper, 'attack').setValue(true)
    expect(wrapper.text()).toContain('failed to load: matrix unavailable')

    await wrapper.find('.retry-btn').trigger('click')
    await flushPromises()

    expect(attackMock).toHaveBeenCalledTimes(2)
    expect(detectionsMock).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.attack-matrix').exists()).toBe(true)
  })

  it('keeps the list usable when only the matrix failed', async () => {
    attackMock.mockResolvedValue(failed('matrix unavailable'))
    const wrapper = await mountTab()
    expect(entryNames(wrapper)).toHaveLength(4)
  })

  it('ignores a technique whose detections are not in the list', async () => {
    attackMock.mockResolvedValue(
      succeeded({
        attack_version: '19.2',
        tactics: [{ id: 'x', name: 'X', techniques: [{ id: 'T1', name: 'T', hit_count: 1, severity: 'low', detection_ids: ['gone'] }] }],
      }),
    )
    const wrapper = await mountTab()
    await modeInput(wrapper, 'attack').setValue(true)
    await wrapper.find('.attack-cell').trigger('click')

    expect(wrapper.find('.technique-filter').exists()).toBe(false)
    expect(entryNames(wrapper)).toHaveLength(4)
  })
})

describe('DetectionsTab matrix selection across rulesets', () => {
  it('shows the detection of another ruleset when its technique is clicked', async () => {
    const wrapper = await mountTab()
    await wrapper.findAll('.radio-input')[1]!.setValue(true)
    await wrapper.findAll('.attack-cell')[2]!.trigger('click')

    expect(entryNames(wrapper)).toEqual(['ET MALWARE Possible beacon'])
  })
})
