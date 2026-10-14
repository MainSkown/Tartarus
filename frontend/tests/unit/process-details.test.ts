import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SeverityBadge from '@/components/SeverityBadge.vue'
import { processDetail, processNode, sampleTree } from './process-fixtures'
import { filterEventsPlugins } from './filter-events-plugins'

const { plugins, router, query } = await filterEventsPlugins()
import type { ProcessNode, ProcessRef } from '@/api'

const viewsProcessMock = vi.fn()
vi.mock('@/api', () => ({ viewsProcess: (...args: unknown[]) => viewsProcessMock(...args) }))

const { default: ProcessDetails } = await import('@/components/ProcessDetails.vue')
const { default: TargetAnnotations } = await import('@/components/TargetAnnotations.vue')
const { processTarget } = await import('@/stores/annotations')

const benign = sampleTree().roots[0]!

interface Options {
  node?: ProcessNode
  injectedInto?: ProcessRef[]
  injectedFrom?: ProcessRef[]
}

async function mountDetails({ node = benign, injectedInto = [], injectedFrom = [] }: Options = {}) {
  const wrapper = mount(ProcessDetails, {
    global: { plugins },
    props: { analysisId: 45, node, injectedInto, injectedFrom },
  })
  await flushPromises()
  return wrapper
}

async function openTab(wrapper: Awaited<ReturnType<typeof mountDetails>>, label: string) {
  const tab = wrapper.findAll('[role="tab"]').find((candidate) => candidate.text().startsWith(label))
  await tab!.trigger('click')
}

function field(wrapper: Awaited<ReturnType<typeof mountDetails>>, label: string): string {
  const term = wrapper.findAll('dt').find((dt) => dt.text() === label)
  if (!term) throw new Error(`no field ${label}`)
  return term.element.nextElementSibling!.textContent!.trim()
}

beforeEach(() => {
  viewsProcessMock.mockReset()
  viewsProcessMock.mockResolvedValue({ data: processDetail(benign) })
})

describe('ProcessDetails tags and note', () => {
  it('are the process by its pid, editable at any time', async () => {
    const section = (await mountDetails()).findComponent(TargetAnnotations)
    expect(section.props()).toMatchObject({ target: processTarget(9708), editable: true })
  })

  it('stay on show while the activity of the process loads or fails', async () => {
    viewsProcessMock.mockResolvedValue({ error: { error: { message: 'index is down' } } })
    expect((await mountDetails()).findComponent(TargetAnnotations).exists()).toBe(true)
  })
})

describe('ProcessDetails fields', () => {
  it('shows the command line, the path, the ids, the times and the duration of the process', async () => {
    const wrapper = await mountDetails()

    expect(field(wrapper, 'COMMAND LINE')).toBe('"C:\\Users\\Analyst\\AppData\\Local\\Temp\\proc9708.exe" /run')
    expect(field(wrapper, 'PATH')).toContain('Temp\\proc9708.exe')
    expect(field(wrapper, 'PID')).toBe('9708')
    expect(field(wrapper, 'PPID')).toBe('4336')
    expect(field(wrapper, 'START (UTC)')).toBe('15:39:50.393')
    expect(field(wrapper, 'END (UTC)')).toBe('15:39:51.706')
    expect(wrapper.findAll('dd').find((dd) => dd.text() === '15:39:50.393')!.attributes('title')).toBe('2026-10-13 15:39:50 UTC')
    expect(field(wrapper, 'DURATION')).toBe('1.3s')
  })

  it('shows a dash for the integrity, which no source reports yet, and for any missing value', async () => {
    const node = processNode(5, { name: null, ppid: null, command_line: null, executable: null, start: null, end: null })
    viewsProcessMock.mockResolvedValue({ data: processDetail(node) })
    const wrapper = await mountDetails({ node })

    for (const label of ['INTEGRITY', 'COMMAND LINE', 'PATH', 'PPID', 'START (UTC)', 'END (UTC)', 'DURATION']) {
      expect(field(wrapper, label)).toBe('–')
    }
  })

  it('shows the integrity level when a source reported one', async () => {
    const node = processNode(5, { integrity: 'High' })
    viewsProcessMock.mockResolvedValue({ data: processDetail(node) })

    expect(field(await mountDetails({ node }), 'INTEGRITY')).toBe('High')
  })

  it('counts the events per lane in lane order, as one row of chips', async () => {
    const wrapper = await mountDetails()

    const chips = wrapper.findAll('.process-details__lane').map((chip) => chip.text())
    expect(chips).toEqual(['PROCESS 1', 'FILE 2', 'REGISTRY 2', 'NETWORK 2', 'API 248'])
  })

  it('shows the detections with their worst severity, or none', async () => {
    const wrapper = await mountDetails()
    expect(wrapper.get('.process-details__header').findComponent(SeverityBadge).props()).toEqual({ severity: 'high', count: 5 })

    const quiet = await mountDetails({ node: processNode(7) })
    expect(quiet.get('.process-details__header').text()).toContain('no detections')
  })

  it('lists the network hosts', async () => {
    expect(field(await mountDetails(), 'NETWORK HOSTS')).toBe('tartarus-selftest.example')
    expect(field(await mountDetails({ node: processNode(7) }), 'NETWORK HOSTS')).toBe('–')
  })

  it('names who the process injected into and who injected into it', async () => {
    const wrapper = await mountDetails({
      injectedInto: [{ pid: 3, name: 'explorer.exe' }],
      injectedFrom: [{ pid: 1, name: 'dropper.exe' }],
    })

    expect(field(wrapper, 'INJECTED INTO')).toBe('explorer.exe (3)')
    expect(field(wrapper, 'INJECTED FROM')).toBe('dropper.exe (1)')
  })

  it('leaves out the injection rows when there is no injection', async () => {
    const wrapper = await mountDetails()

    expect(wrapper.findAll('dt').map((dt) => dt.text())).not.toContain('INJECTED INTO')
    expect(wrapper.findAll('dt').map((dt) => dt.text())).not.toContain('INJECTED FROM')
  })
})

describe('ProcessDetails loaded detail', () => {
  it('loads the process of the analysis by pid', async () => {
    await mountDetails()

    expect(viewsProcessMock).toHaveBeenCalledWith({ path: { analysis_id: 45, pid: 9708 } })
  })

  it('shows the fields while the rest is loading', async () => {
    viewsProcessMock.mockReturnValue(new Promise(() => undefined))
    const wrapper = mount(ProcessDetails, {
      global: { plugins },
      props: { analysisId: 45, node: benign, injectedInto: [], injectedFrom: [] },
    })
    await flushPromises()

    expect(wrapper.find('.loader').exists()).toBe(true)
    expect(field(wrapper, 'PID')).toBe('9708')
  })

  it('has a sub-tab each for the top APIs, the modules and the events, labelled with their counts', async () => {
    const wrapper = await mountDetails()

    const tabs = wrapper.findAll('[role="tab"]').map((tab) => tab.text())
    expect(tabs).toEqual(['TOP APIS 2', 'MODULES 2', 'EVENTS 7'])
  })

  it('opens on the top APIs with their counts', async () => {
    const wrapper = await mountDetails()

    expect(wrapper.get('[role="tab"][aria-selected="true"]').text()).toContain('TOP APIS')
    const rows = wrapper.findAll('.process-details__apis tbody tr').map((row) => row.text())
    expect(rows).toEqual(['NtClose40', 'NtWriteFile29'])
    expect(wrapper.find('.process-details__events').exists()).toBe(false)
  })

  it('shows the events, and how many of the total, under the events sub-tab', async () => {
    const wrapper = await mountDetails()

    await openTab(wrapper, 'EVENTS')

    expect(wrapper.get('.process-details__events').text()).toContain('DNS query for tartarus-selftest.example')
    expect(wrapper.text()).toContain('1 of 7')
    expect(wrapper.find('.process-details__apis').exists()).toBe(false)
  })

  it('shows the modules with their base address and path under the modules sub-tab', async () => {
    const wrapper = await mountDetails()

    await openTab(wrapper, 'MODULES')

    const modules = wrapper.get('.process-details__modules').text()
    expect(modules).toContain('0x7ffd9ae50000')
    expect(modules).toContain('C:\\WINDOWS\\SYSTEM32\\DNSAPI')
  })

  it('says so when there is nothing recorded for the process', async () => {
    viewsProcessMock.mockResolvedValue({ data: processDetail(benign, { modules: [], top_apis: [], events: [], event_total: 0 }) })
    const wrapper = await mountDetails()

    await openTab(wrapper, 'EVENTS')
    expect(wrapper.text()).toContain('> no events recorded')
    await openTab(wrapper, 'MODULES')
    expect(wrapper.text()).toContain('> no modules recorded')
    await openTab(wrapper, 'TOP APIS')
    expect(wrapper.text()).toContain('> no API calls recorded')
  })

  it('shows its own error with a retry that loads again', async () => {
    viewsProcessMock.mockResolvedValueOnce({ error: { error: { message: 'index is down' } } })
    const wrapper = await mountDetails()
    expect(wrapper.text()).toContain('failed to load: index is down')
    expect(field(wrapper, 'PID')).toBe('9708')
    viewsProcessMock.mockResolvedValue({ data: processDetail(benign) })

    await wrapper.get('.retry-btn').trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('failed to load')
    expect(wrapper.find('.process-details__apis').exists()).toBe(true)
  })
})

describe('ProcessDetails show events', () => {
  beforeEach(() => query.reset())

  it('has a button that names the process it shows events for', async () => {
    const wrapper = await mountDetails()
    const button = wrapper.get('.process-details__header button')
    expect(button.attributes('aria-label')).toBe('Show events with pid: 9708')
    expect(button.attributes('title')).toBe('Show events')
  })

  it('limits the events to this process and opens the Events tab', async () => {
    const wrapper = await mountDetails()
    await wrapper.get('.process-details__header button').trigger('click')
    await flushPromises()
    expect(query.pids).toEqual([9708])
    expect(router.currentRoute.value.params.tab).toBe('events')
  })
})
