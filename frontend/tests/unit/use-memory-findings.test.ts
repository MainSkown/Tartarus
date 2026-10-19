import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'
import { eventFixture, eventPage } from './events-fixtures'

const eventsSearch = vi.hoisted(() => vi.fn())
vi.mock('@/api', () => ({ eventsSearch }))

const { useMemoryFindings } = await import('@/composables/use-memory-findings')

function finding(id: string, plugin = 'windows.malware.malfind') {
  return eventFixture({
    id,
    kind: 'alert',
    severity: 'high',
    process: { pid: 2184, name: 'notepad.exe', entity_id: null },
    fields: { 'tartarus.memory.plugin': plugin, 'tartarus.memory.address': `0x${id}` },
  })
}

function mountFindings(enabled = true) {
  const analysisId = ref(45)
  const isEnabled = ref(enabled)
  const scope = effectScope()
  const findings = scope.run(() => useMemoryFindings(() => analysisId.value, () => isEnabled.value))!
  return { findings, analysisId, isEnabled }
}

beforeEach(() => {
  eventsSearch.mockReset()
  eventsSearch.mockResolvedValue({ data: eventPage([finding('a1'), finding('b2', 'windows.malware.hollowprocesses')]), response: { status: 200 } })
})

describe('useMemoryFindings', () => {
  it('searches the Volatility detections of the analysis once, quietly (the tab shows the failure itself)', async () => {
    mountFindings()
    await flushPromises()
    expect(eventsSearch).toHaveBeenCalledTimes(1)
    const call = eventsSearch.mock.calls[0]![0]
    expect(call.path).toEqual({ analysis_id: 45 })
    expect(call.body.filters).toContainEqual({ field: 'event.module', value: 'volatility' })
    expect(call.body.columns).toContain('tartarus.memory.address')
    expect(call.meta).toEqual({ quietStatuses: [422, 502, 504] })
  })

  it('exposes the findings and how many the index holds in all', async () => {
    eventsSearch.mockResolvedValue({ data: eventPage([finding('a1')], { total: 1200 }), response: { status: 200 } })
    const { findings } = mountFindings()
    expect(findings.loading.value).toBe(true)
    await flushPromises()
    expect(findings.loading.value).toBe(false)
    expect(findings.findings.value.map((item) => item.id)).toEqual(['a1'])
    expect(findings.total.value).toBe(1200)
    expect(findings.truncated.value).toBe(true)
  })

  it('is not truncated when every finding was returned', async () => {
    const { findings } = mountFindings()
    await flushPromises()
    expect(findings.total.value).toBe(2)
    expect(findings.truncated.value).toBe(false)
  })

  it('asks for nothing when there is no dump to read, and has no findings', async () => {
    const { findings } = mountFindings(false)
    await flushPromises()
    expect(eventsSearch).not.toHaveBeenCalled()
    expect(findings.findings.value).toEqual([])
    expect(findings.loading.value).toBe(false)
    expect(findings.counted.value).toBeUndefined()
  })

  it('counts the findings once they are loaded', async () => {
    const { findings } = mountFindings()
    expect(findings.counted.value).toBeUndefined()
    await flushPromises()
    expect(findings.counted.value).toBe(2)
  })

  it('exposes the error and no findings when the search fails, and tries again on reload', async () => {
    eventsSearch.mockResolvedValueOnce({ error: { error: { code: 'x', message: 'OpenSearch is not answering' } }, response: { status: 502 } })
    const { findings } = mountFindings()
    await flushPromises()
    expect(findings.error.value).toBe('OpenSearch is not answering')
    expect(findings.findings.value).toEqual([])
    expect(findings.counted.value).toBeUndefined()
    await findings.reload()
    expect(findings.error.value).toBeUndefined()
    expect(findings.findings.value).toHaveLength(2)
  })

  it('asks again for another analysis', async () => {
    const { analysisId } = mountFindings()
    await flushPromises()
    analysisId.value = 46
    await flushPromises()
    expect(eventsSearch).toHaveBeenCalledTimes(2)
    expect(eventsSearch.mock.calls[1]![0].path).toEqual({ analysis_id: 46 })
  })

  it('asks when the dump becomes readable', async () => {
    const { isEnabled, findings } = mountFindings(false)
    await flushPromises()
    isEnabled.value = true
    await flushPromises()
    expect(eventsSearch).toHaveBeenCalledTimes(1)
    expect(findings.findings.value).toHaveLength(2)
  })
})
