import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisPage, AnalysisRead, AnalysisStatus, ErrorEnvelope } from '@/api'

const analysesListMock = vi.fn()
const analysesCreateMock = vi.fn()
const analysesReadMock = vi.fn()
const analysesCancelMock = vi.fn()
const analysesDeleteMock = vi.fn()
const analysesReingestMock = vi.fn()
vi.mock('@/api', () => ({
  analysesList: (...args: unknown[]) => analysesListMock(...args),
  analysesCreate: (...args: unknown[]) => analysesCreateMock(...args),
  analysesRead: (...args: unknown[]) => analysesReadMock(...args),
  analysesCancel: (...args: unknown[]) => analysesCancelMock(...args),
  analysesDelete: (...args: unknown[]) => analysesDeleteMock(...args),
  analysesReingest: (...args: unknown[]) => analysesReingestMock(...args),
}))

const { SubmissionRejected, useAnalysesStore } = await import('@/stores/analyses')
const { quietOn } = await import('@/services/quiet-statuses')

const POLL_MS = 2_000
const BACKOFF_MS = 10_000

function analysis(id: number, status: AnalysisStatus = 'done'): AnalysisRead {
  return {
    id,
    sample_sha256: 'a'.repeat(64),
    filename: `sample-${id}.exe`,
    cape_task_id: null,
    queue_position: null,
    status,
    phase: 'live',
    options: {},
    score: null,
    max_severity: null,
    detected_families: [],
    event_count: 0,
    disk_bytes: 0,
    error: null,
    submitted_at: '2026-10-13T10:00:00Z',
    started_at: null,
    finished_at: null,
    summary: null,
    tags: [],
    guest: null,
    guest_badges: [],
  }
}

function page(...items: AnalysisRead[]): AnalysisPage {
  return { items, total: items.length }
}

const succeeded = <T>(data: T) => ({ data, error: undefined })

function failed(
  code = 'internal_error',
  message = 'boom',
  fields: { location: string[]; message: string }[] = [],
  status = 500,
) {
  const error: ErrorEnvelope = {
    error: {
      code,
      message,
      details: fields.length > 0 ? { fields: fields.map((f) => ({ ...f, type: 'value_error' })) } : {},
    },
  }
  return { data: undefined, error, response: { status } }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

async function tick(ms: number): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms)
}

let store: ReturnType<typeof useAnalysesStore>

beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  analysesListMock.mockReset().mockResolvedValue(succeeded(page()))
  analysesCreateMock.mockReset()
  analysesReadMock.mockReset()
  analysesCancelMock.mockReset()
  analysesDeleteMock.mockReset().mockResolvedValue(succeeded(undefined))
  store = useAnalysesStore()
})

afterEach(() => {
  store.$dispose()
  vi.useRealTimers()
})

describe('fetchList', () => {
  it('sends the query to the client and stores the page', async () => {
    analysesListMock.mockResolvedValue(succeeded({ items: [analysis(2), analysis(1)], total: 9 }))
    await store.fetchList({ q: 'evil', status: 'done', limit: 25, offset: 50 })
    expect(analysesListMock).toHaveBeenCalledWith({ query: { q: 'evil', status: 'done', limit: 25, offset: 50 } })
    expect(store.items.map((item) => item.id)).toEqual([2, 1])
    expect(store.total).toBe(9)
    expect(store.loadError).toBeUndefined()
  })

  it('is loading while the request is in flight', async () => {
    const pending = deferred<unknown>()
    analysesListMock.mockReturnValue(pending.promise)
    const request = store.fetchList()
    expect(store.loading).toBe(true)
    pending.resolve(succeeded(page()))
    await request
    expect(store.loading).toBe(false)
  })

  it('records the error message and keeps the previous items on failure', async () => {
    analysesListMock.mockResolvedValueOnce(succeeded(page(analysis(1))))
    await store.fetchList()
    analysesListMock.mockResolvedValue(failed('internal_error', 'database is down'))
    await store.fetchList()
    expect(store.loadError).toBe('database is down')
    expect(store.items.map((item) => item.id)).toEqual([1])
    expect(store.loading).toBe(false)
  })

  it('clears the error once a later fetch succeeds', async () => {
    analysesListMock.mockResolvedValueOnce(failed())
    await store.fetchList()
    expect(store.loadError).toBeDefined()
    await store.fetchList()
    expect(store.loadError).toBeUndefined()
  })

  it('ignores a stale response that arrives after a newer one', async () => {
    const slow = deferred<unknown>()
    analysesListMock.mockReturnValueOnce(slow.promise)
    const first = store.fetchList({ q: 'old' })
    analysesListMock.mockResolvedValueOnce(succeeded(page(analysis(2))))
    await store.fetchList({ q: 'new' })
    slow.resolve(succeeded(page(analysis(1))))
    await first
    expect(store.items.map((item) => item.id)).toEqual([2])
  })
})

describe('fetchOne', () => {
  it('reads the analysis by id into current', async () => {
    analysesReadMock.mockResolvedValue(succeeded(analysis(7, 'running')))
    await store.fetchOne(7)
    expect(analysesReadMock).toHaveBeenCalledWith(expect.objectContaining({ path: { analysis_id: 7 } }))
    expect(store.current?.id).toBe(7)
  })

  it('drops the previously viewed analysis while another one loads', async () => {
    analysesReadMock.mockResolvedValueOnce(succeeded(analysis(1)))
    await store.fetchOne(1)
    const pending = deferred<unknown>()
    analysesReadMock.mockReturnValueOnce(pending.promise)
    const request = store.fetchOne(2)
    expect(store.current).toBeUndefined()
    pending.resolve(succeeded(analysis(2)))
    await request
    expect(store.current?.id).toBe(2)
  })

  it('records the error and leaves current empty when the analysis does not exist', async () => {
    analysesReadMock.mockResolvedValue(failed('not_found', 'Analysis 9 not found', [], 404))
    await store.fetchOne(9)
    expect(store.current).toBeUndefined()
    expect(store.loadError).toBe('Analysis 9 not found')
  })

  it('keeps the HTTP status of the failure so a missing analysis can be told from a broken backend', async () => {
    analysesReadMock.mockResolvedValue(failed('not_found', 'Analysis 9 not found', [], 404))
    await store.fetchOne(9)
    expect(store.loadErrorStatus).toBe(404)

    analysesReadMock.mockResolvedValue(failed('internal_error', 'database is down'))
    await store.fetchOne(9)
    expect(store.loadErrorStatus).toBe(500)
  })

  it('clears the failure status once a read succeeds', async () => {
    analysesReadMock.mockResolvedValue(failed('not_found', 'Analysis 9 not found', [], 404))
    await store.fetchOne(9)
    analysesReadMock.mockResolvedValue(succeeded(analysis(9)))
    await store.fetchOne(9)
    expect(store.loadErrorStatus).toBeUndefined()
    expect(store.loadError).toBeUndefined()
  })

  it('asks the API client not to toast a 404, which the page shows itself', async () => {
    analysesReadMock.mockResolvedValue(succeeded(analysis(7)))
    await store.fetchOne(7)
    expect(analysesReadMock).toHaveBeenCalledWith(expect.objectContaining({ meta: quietOn(404) }))
  })
})

describe('submit', () => {
  const file = new File(['MZ'], 'benign.exe')

  it('posts the file and the options as a JSON string, and returns the analysis', async () => {
    analysesCreateMock.mockResolvedValue(succeeded(analysis(5, 'queued')))
    const created = await store.submit(file, { route: 'inetsim', timeout: 120, package: 'exe' })
    expect(created.id).toBe(5)
    const [{ body }] = analysesCreateMock.mock.calls[0] as [{ body: { file: File; options: string } }]
    expect(body.file).toBe(file)
    expect(typeof body.options).toBe('string')
    expect(JSON.parse(body.options)).toEqual({ route: 'inetsim', timeout: 120, package: 'exe' })
  })

  it('leaves the package out when none is chosen so the backend default applies', async () => {
    analysesCreateMock.mockResolvedValue(succeeded(analysis(5, 'queued')))
    await store.submit(file, { route: 'none', timeout: 60 })
    const [{ body }] = analysesCreateMock.mock.calls[0] as [{ body: { options: string } }]
    expect(JSON.parse(body.options)).toEqual({ route: 'none', timeout: 60 })
  })

  it('rejects with the per-field messages of a 422', async () => {
    analysesCreateMock.mockResolvedValue(
      failed('validation_error', 'Request validation failed', [
        { location: ['body', 'options', 'timeout'], message: 'Input should be at least 60' },
      ]),
    )
    const rejection = await store.submit(file, { route: 'none', timeout: 5 }).catch((error: unknown) => error)
    expect(rejection).toBeInstanceOf(SubmissionRejected)
    expect((rejection as InstanceType<typeof SubmissionRejected>).issues).toEqual([
      { field: 'timeout', message: 'Input should be at least 60' },
    ])
  })

  it('rejects with the envelope message and no issues for any other failure', async () => {
    analysesCreateMock.mockResolvedValue(failed('guest_not_ready', 'The analysis guest is not ready'))
    const rejection = await store.submit(file, { route: 'none', timeout: 60 }).catch((error: unknown) => error)
    expect(rejection).toBeInstanceOf(SubmissionRejected)
    expect((rejection as Error).message).toBe('The analysis guest is not ready')
    expect((rejection as InstanceType<typeof SubmissionRejected>).issues).toEqual([])
  })
})

describe('cancel', () => {
  it('replaces the analysis in items and current with the cancelled one', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(2, 'queued'), analysis(1, 'running'))))
    analysesReadMock.mockResolvedValue(succeeded(analysis(2, 'queued')))
    await store.fetchList()
    await store.fetchOne(2)
    analysesCancelMock.mockResolvedValue(succeeded(analysis(2, 'cancelled')))

    expect(await store.cancel(2)).toBe(true)
    expect(analysesCancelMock).toHaveBeenCalledWith({ path: { analysis_id: 2 } })
    expect(store.items.map((item) => item.status)).toEqual(['cancelled', 'running'])
    expect(store.current?.status).toBe('cancelled')
  })

  it('reports false and changes nothing when the backend refuses', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'running'))))
    await store.fetchList()
    analysesCancelMock.mockResolvedValue(failed('conflict', 'Only a queued analysis can be cancelled'))
    expect(await store.cancel(1)).toBe(false)
    expect(store.items[0]?.status).toBe('running')
  })
})

describe('reingest', () => {
  it('replaces the analysis in items and current with the one now ingesting, and polls it', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(2, 'done'), analysis(1, 'done'))))
    analysesReadMock.mockResolvedValue(succeeded(analysis(2, 'done')))
    await store.fetchList()
    await store.fetchOne(2)
    store.startPolling()
    analysesReingestMock.mockResolvedValue(succeeded(analysis(2, 'ingesting')))

    expect(await store.reingest(2)).toBe(true)
    expect(analysesReingestMock).toHaveBeenCalledWith({ path: { analysis_id: 2 } })
    expect(store.items.map((item) => item.status)).toEqual(['ingesting', 'done'])
    expect(store.current?.status).toBe('ingesting')

    analysesListMock.mockClear()
    await vi.advanceTimersByTimeAsync(POLL_MS)
    expect(analysesListMock).toHaveBeenCalled()
  })

  it('reports false and changes nothing when the backend refuses', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'done'))))
    await store.fetchList()
    analysesReingestMock.mockResolvedValue(failed('conflict', 'Another analysis is active', [], 409))
    expect(await store.reingest(1)).toBe(false)
    expect(store.items[0]?.status).toBe('done')
  })
})

describe('setTags', () => {
  it('puts the analysis tags on the row and the open analysis', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(2), analysis(1))))
    analysesReadMock.mockResolvedValue(succeeded(analysis(2)))
    await store.fetchList()
    await store.fetchOne(2)

    store.setTags(2, ['emotet', 'phishing'])

    expect(store.items.map((item) => item.tags)).toEqual([['emotet', 'phishing'], []])
    expect(store.current?.tags).toEqual(['emotet', 'phishing'])
  })

  it('ignores an analysis it does not hold', () => {
    expect(() => store.setTags(99, ['x'])).not.toThrow()
  })
})

describe('remove', () => {
  beforeEach(async () => {
    analysesListMock.mockResolvedValue({ data: { items: [analysis(2), analysis(1)], total: 2 }, error: undefined })
    await store.fetchList()
  })

  it('deletes through the client and drops the analysis from items', async () => {
    expect(await store.remove(1)).toBe(true)
    expect(analysesDeleteMock).toHaveBeenCalledWith({ path: { analysis_id: 1 } })
    expect(store.items.map((item) => item.id)).toEqual([2])
    expect(store.total).toBe(1)
  })

  it('clears current when it is the removed analysis', async () => {
    analysesReadMock.mockResolvedValue(succeeded(analysis(1)))
    await store.fetchOne(1)
    await store.remove(1)
    expect(store.current).toBeUndefined()
  })

  it('keeps current when another analysis is removed', async () => {
    analysesReadMock.mockResolvedValue(succeeded(analysis(1)))
    await store.fetchOne(1)
    await store.remove(2)
    expect(store.current?.id).toBe(1)
  })

  it('keeps everything and reports false when the backend refuses', async () => {
    analysesDeleteMock.mockResolvedValue(failed('conflict', 'Analysis is running'))
    expect(await store.remove(1)).toBe(false)
    expect(store.items).toHaveLength(2)
    expect(store.total).toBe(2)
  })
})

describe('polling the list', () => {
  it('refreshes every 2 seconds while a listed analysis is queued', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'queued'))))
    await store.fetchList({ limit: 10 })
    store.startPolling()
    expect(analysesListMock).toHaveBeenCalledTimes(1)

    await tick(POLL_MS)
    expect(analysesListMock).toHaveBeenCalledTimes(2)
    expect(analysesListMock).toHaveBeenLastCalledWith({ query: { limit: 10 } })
    await tick(POLL_MS)
    expect(analysesListMock).toHaveBeenCalledTimes(3)
  })

  it.each<AnalysisStatus>(['starting', 'running', 'processing', 'ingesting'])(
    'keeps refreshing while an analysis is %s',
    async (status) => {
      analysesListMock.mockResolvedValue(succeeded(page(analysis(1, status))))
      await store.fetchList()
      store.startPolling()
      await tick(POLL_MS)
      expect(analysesListMock).toHaveBeenCalledTimes(2)
    },
  )

  it('picks up the new status and stops by itself once everything is terminal', async () => {
    analysesListMock.mockResolvedValueOnce(succeeded(page(analysis(1, 'running'))))
    await store.fetchList()
    store.startPolling()
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'done'))))

    await tick(POLL_MS)
    expect(store.items[0]?.status).toBe('done')
    expect(analysesListMock).toHaveBeenCalledTimes(2)

    await tick(60_000)
    expect(analysesListMock).toHaveBeenCalledTimes(2)
  })

  it('does nothing when nothing needs refreshing', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'done'))))
    await store.fetchList()
    store.startPolling()
    await tick(60_000)
    expect(analysesListMock).toHaveBeenCalledTimes(1)
  })

  it('does not stack timers when started twice', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'queued'))))
    await store.fetchList()
    store.startPolling()
    store.startPolling()
    await tick(POLL_MS)
    expect(analysesListMock).toHaveBeenCalledTimes(2)
  })

  it('does not stack timers when a fetch lands between ticks', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'queued'))))
    await store.fetchList()
    store.startPolling()
    await tick(1_000)
    await store.fetchList()
    await tick(1_000)
    expect(analysesListMock).toHaveBeenCalledTimes(3)
  })

  it('restarts after a submit when the list had gone quiet', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'done'))))
    await store.fetchList()
    store.startPolling()
    await tick(POLL_MS)
    expect(analysesListMock).toHaveBeenCalledTimes(1)

    analysesCreateMock.mockResolvedValue(succeeded(analysis(2, 'queued')))
    analysesListMock.mockResolvedValue(succeeded(page(analysis(2, 'queued'), analysis(1, 'done'))))
    await store.submit(new File(['MZ'], 'a.exe'), { route: 'none', timeout: 60 })
    expect(store.items.map((item) => item.id)).toEqual([2, 1])
    const callsAfterSubmit = analysesListMock.mock.calls.length

    await tick(POLL_MS)
    expect(analysesListMock.mock.calls.length).toBe(callsAfterSubmit + 1)
  })

  it('restarts when a later fetch shows work to track', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'done'))))
    await store.fetchList()
    store.startPolling()
    analysesListMock.mockResolvedValue(succeeded(page(analysis(2, 'queued'))))
    await store.fetchList({ status: 'queued' })
    await tick(POLL_MS)
    expect(analysesListMock).toHaveBeenCalledTimes(3)
    expect(analysesListMock).toHaveBeenLastCalledWith({ query: { status: 'queued' } })
  })

  it('stays stopped after stopPolling, even if a fetch shows work to track', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'queued'))))
    await store.fetchList()
    store.startPolling()
    store.stopPolling()
    await store.fetchList()
    await tick(60_000)
    expect(analysesListMock).toHaveBeenCalledTimes(2)
  })

  it('skips ticks while the previous request is still in flight', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'running'))))
    await store.fetchList()
    store.startPolling()

    const slow = deferred<unknown>()
    analysesListMock.mockReturnValueOnce(slow.promise)
    await tick(POLL_MS)
    expect(analysesListMock).toHaveBeenCalledTimes(2)

    await tick(30_000)
    expect(analysesListMock).toHaveBeenCalledTimes(2)

    slow.resolve(succeeded(page(analysis(1, 'running'))))
    await tick(POLL_MS)
    expect(analysesListMock).toHaveBeenCalledTimes(3)
  })
})

describe('polling the viewed analysis', () => {
  it('refreshes current every 2 seconds until it is terminal', async () => {
    analysesReadMock.mockResolvedValueOnce(succeeded(analysis(4, 'running')))
    await store.fetchOne(4)
    store.startPolling()

    analysesReadMock.mockResolvedValueOnce(succeeded(analysis(4, 'processing')))
    await tick(POLL_MS)
    expect(store.current?.status).toBe('processing')
    expect(analysesReadMock).toHaveBeenLastCalledWith(expect.objectContaining({ path: { analysis_id: 4 } }))

    analysesReadMock.mockResolvedValue(succeeded(analysis(4, 'done')))
    await tick(POLL_MS)
    expect(store.current?.status).toBe('done')
    expect(analysesReadMock).toHaveBeenCalledTimes(3)

    await tick(60_000)
    expect(analysesReadMock).toHaveBeenCalledTimes(3)
  })

  it('does not touch the list while only current needs refreshing', async () => {
    analysesReadMock.mockResolvedValue(succeeded(analysis(4, 'running')))
    await store.fetchOne(4)
    store.startPolling()
    await tick(POLL_MS)
    expect(analysesListMock).not.toHaveBeenCalled()
  })

  it('refreshes list and current in the same tick when both need it', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(4, 'running'))))
    analysesReadMock.mockResolvedValue(succeeded(analysis(4, 'running')))
    await store.fetchList()
    await store.fetchOne(4)
    store.startPolling()
    await tick(POLL_MS)
    expect(analysesListMock).toHaveBeenCalledTimes(2)
    expect(analysesReadMock).toHaveBeenCalledTimes(2)
  })

  it('applies a poll result only to the analysis still being viewed', async () => {
    analysesReadMock.mockResolvedValueOnce(succeeded(analysis(4, 'running')))
    await store.fetchOne(4)
    store.startPolling()

    const slow = deferred<unknown>()
    analysesReadMock.mockReturnValueOnce(slow.promise)
    await tick(POLL_MS)
    analysesReadMock.mockResolvedValueOnce(succeeded(analysis(8, 'running')))
    await store.fetchOne(8)
    slow.resolve(succeeded(analysis(4, 'done')))
    await tick(0)
    expect(store.current?.id).toBe(8)
  })
})

describe('polling failures', () => {
  it('backs off to 10 seconds after 3 consecutive failures and recovers on success', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'running'))))
    await store.fetchList()
    store.startPolling()
    analysesListMock.mockResolvedValue(failed())

    await tick(POLL_MS)
    await tick(POLL_MS)
    await tick(POLL_MS)
    expect(analysesListMock).toHaveBeenCalledTimes(4)

    await tick(BACKOFF_MS - 1)
    expect(analysesListMock).toHaveBeenCalledTimes(4)
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'running'))))
    await tick(1)
    expect(analysesListMock).toHaveBeenCalledTimes(5)

    await tick(POLL_MS)
    expect(analysesListMock).toHaveBeenCalledTimes(6)
  })

  it('keeps the 2 second cadence when failures are not consecutive', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'running'))))
    await store.fetchList()
    store.startPolling()

    for (const outcome of [failed(), failed(), succeeded(page(analysis(1, 'running'))), failed(), failed()]) {
      analysesListMock.mockResolvedValueOnce(outcome)
      await tick(POLL_MS)
    }
    expect(analysesListMock).toHaveBeenCalledTimes(6)
  })

  it('does not raise errors of its own for failed polls', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'running'))))
    await store.fetchList()
    store.startPolling()
    analysesListMock.mockResolvedValue(failed())
    await expect(tick(POLL_MS)).resolves.toBeUndefined()
  })
})

describe('disposal', () => {
  it('clears the poll timer so nothing fires afterwards', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'running'))))
    await store.fetchList()
    store.startPolling()
    store.$dispose()
    await tick(60_000)
    expect(analysesListMock).toHaveBeenCalledTimes(1)
  })

  it('does not schedule another poll when a request finishes after disposal', async () => {
    analysesListMock.mockResolvedValue(succeeded(page(analysis(1, 'running'))))
    await store.fetchList()
    store.startPolling()
    const slow = deferred<unknown>()
    analysesListMock.mockReturnValueOnce(slow.promise)
    await tick(POLL_MS)
    store.$dispose()
    slow.resolve(succeeded(page(analysis(1, 'running'))))
    await tick(60_000)
    expect(analysesListMock).toHaveBeenCalledTimes(2)
  })
})
