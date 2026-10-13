import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import type { AnalysisStatus } from '@/api'
import { ARTIFACTS_VIEW } from './detections-fixtures'

vi.mock('@/api', () => ({ viewsArtifacts: vi.fn() }))

const { viewsArtifacts } = await import('@/api')
const { useLastScreenshot } = await import('@/composables/use-last-screenshot')

const artifactsMock = vi.mocked(viewsArtifacts)

async function load(status: () => AnalysisStatus) {
  let api!: ReturnType<typeof useLastScreenshot>
  mount(
    defineComponent({
      setup() {
        api = useLastScreenshot(() => 45, status)
        return () => h('div')
      },
    }),
  )
  await flushPromises()
  return api
}

beforeEach(() => {
  artifactsMock.mockResolvedValue({ data: ARTIFACTS_VIEW, error: undefined } as never)
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('useLastScreenshot', () => {
  it('looks again when a running analysis turns done, since the report is new then', async () => {
    const status = ref<AnalysisStatus>('running')
    const api = await load(() => status.value)
    expect(api.last.value).toBe(0)
    expect(artifactsMock).not.toHaveBeenCalled()
    status.value = 'done'
    await flushPromises()
    expect(api.last.value).toBe(3)
  })

  it('finds the highest numbered screenshot of a finished report and counts them', async () => {
    const shots = await load(() => 'done')
    expect(shots.last.value).toBe(3)
    expect(shots.count.value).toBe(3)
    expect(artifactsMock).toHaveBeenCalledWith({ path: { analysis_id: 45 } })
  })

  it('does not ask for screenshots of a run that has no report', async () => {
    const shots = await load(() => 'failed')
    expect(artifactsMock).not.toHaveBeenCalled()
    expect(shots.last.value).toBe(0)
  })

  it('reports a failed request instead of throwing', async () => {
    artifactsMock.mockResolvedValue({ data: undefined, error: { detail: 'boom' } } as never)
    const shots = await load(() => 'done')
    expect(shots.error.value).toBeDefined()
    expect(shots.last.value).toBe(0)
  })
})
