import { createPinia, setActivePinia } from 'pinia'
import { reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { QueueSnapshot, RunningAnalysis, QueuedAnalysis } from '@/api'

vi.mock('@/api', () => ({ systemQueue: vi.fn() }))

const system = reactive({ onQueue: vi.fn() })
let pushQueue: ((snapshot: QueueSnapshot) => void) | undefined
vi.mock('@/stores/system', () => ({ useSystemStore: () => system }))

const { systemQueue } = await import('@/api')
const { useQueueStore } = await import('@/stores/queue')

let created: ReturnType<typeof useQueueStore> | undefined

function running(id: number, guest: string | null = 'lab1'): RunningAnalysis {
  return {
    id,
    filename: `sample-${id}.exe`,
    guest,
    status: 'running',
    started_at: '2026-10-21T10:00:00Z',
    elapsed_s: 72,
  }
}

function queued(id: number, position: number, guest: string | null = 'lab1'): QueuedAnalysis {
  return { id, filename: `queued-${id}.exe`, guest, position }
}

function snapshot(runningItems: RunningAnalysis[], queuedItems: QueuedAnalysis[] = []): QueueSnapshot {
  return { running: runningItems, queued_count: queuedItems.length, queued: queuedItems }
}

function serveQueue(data: QueueSnapshot): void {
  vi.mocked(systemQueue).mockResolvedValue({ data } as never)
}

function freshStore() {
  setActivePinia(createPinia())
  created = useQueueStore()
  return created
}

beforeEach(() => {
  vi.mocked(systemQueue).mockReset()
  system.onQueue.mockReset().mockImplementation((handler: (snapshot: QueueSnapshot) => void) => {
    pushQueue = handler
    return () => {
      pushQueue = undefined
    }
  })
})

afterEach(() => {
  created?.$dispose()
  created = undefined
})

describe('useQueueStore initial fetch', () => {
  it('loads the queue from GET /api/system/queue on creation', async () => {
    serveQueue(snapshot([running(42)], [queued(43, 1)]))
    const queue = freshStore()

    await vi.waitFor(() => expect(queue.runningCount).toBe(1))
    expect(systemQueue).toHaveBeenCalledOnce()
    expect(queue.queuedCount).toBe(1)
  })

  it('ignores a fetch that resolves after a newer push', async () => {
    let answer: (value: unknown) => void = () => undefined
    vi.mocked(systemQueue).mockReturnValue(new Promise((resolve) => (answer = resolve)) as never)
    const queue = freshStore()

    pushQueue?.(snapshot([running(1), running(2)]))
    answer({ data: snapshot([]) })
    await vi.waitFor(() => expect(systemQueue).toHaveBeenCalled())

    expect(queue.runningCount).toBe(2)
  })
})

describe('useQueueStore pushes', () => {
  it('replaces the snapshot with each queue push', async () => {
    serveQueue(snapshot([]))
    const queue = freshStore()
    await vi.waitFor(() => expect(systemQueue).toHaveBeenCalled())

    pushQueue?.(snapshot([running(7)], [queued(8, 1)]))

    expect(queue.runningCount).toBe(1)
    expect(queue.queuedCount).toBe(1)
  })

  it('stops listening once disposed', async () => {
    serveQueue(snapshot([]))
    const queue = freshStore()
    queue.$dispose()
    created = undefined
    expect(pushQueue).toBeUndefined()
  })
})

describe('useQueueStore running counts', () => {
  it.each([
    [0, []],
    [1, [running(42)]],
    [3, [running(41), running(42), running(43, 'lab2')]],
  ])('reports %i running analyses with their list', async (count, items) => {
    serveQueue(snapshot(items))
    const queue = freshStore()
    pushQueue?.(snapshot(items))

    expect(queue.runningCount).toBe(count)
    expect(queue.running.map((analysis) => analysis.id)).toEqual(items.map((analysis) => analysis.id))
  })
})

describe('useQueueStore lookups', () => {
  it('finds the queue entry of a queued analysis by id', async () => {
    serveQueue(snapshot([], [queued(9, 2, 'lab3')]))
    const queue = freshStore()
    pushQueue?.(snapshot([], [queued(9, 2, 'lab3')]))

    expect(queue.queuedEntryOf(9)).toEqual(queued(9, 2, 'lab3'))
    expect(queue.queuedEntryOf(10)).toBeUndefined()
  })

  it('marks a guest busy while it runs or has a queued analysis, and free otherwise', async () => {
    serveQueue(snapshot([running(1, 'lab1')], [queued(2, 1, 'lab2')]))
    const queue = freshStore()
    pushQueue?.(snapshot([running(1, 'lab1')], [queued(2, 1, 'lab2')]))

    expect(queue.guestBusy('lab1')).toBe(true)
    expect(queue.guestBusy('lab2')).toBe(true)
    expect(queue.guestBusy('lab3')).toBe(false)
  })
})

