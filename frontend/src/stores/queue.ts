import { defineStore } from 'pinia'
import { computed, onScopeDispose, ref } from 'vue'
import { systemQueue } from '@/api'
import type { QueuedAnalysis, QueueSnapshot, RunningAnalysis } from '@/api'
import { useSystemStore } from '@/stores/system'

const EMPTY_QUEUE: QueueSnapshot = { running: [], queued_count: 0, queued: [] }

/**
 * The one source of truth for what runs and what waits: the snapshot `GET /api/system/queue`
 * returns, replaced by every `queue` push on `/ws/system`. The header's live chip, the Submit
 * dialog's busy guests and the Dashboard's queue positions all read from here.
 */
export const useQueueStore = defineStore('queue', () => {
  const system = useSystemStore()
  const snapshot = ref<QueueSnapshot>(EMPTY_QUEUE)
  // A fetch started before a push must not overwrite the newer push when it resolves late.
  let pushes = 0

  const running = computed<RunningAnalysis[]>(() => snapshot.value.running)
  const runningCount = computed(() => running.value.length)
  const queuedCount = computed(() => snapshot.value.queued_count)

  function apply(next: QueueSnapshot): void {
    snapshot.value = next
  }

  function applyPush(next: QueueSnapshot): void {
    pushes += 1
    apply(next)
  }

  async function load(): Promise<void> {
    const pushesBefore = pushes
    const { data } = await systemQueue()
    if (data && pushes === pushesBefore) apply(data)
  }

  function queuedEntryOf(analysisId: number): QueuedAnalysis | undefined {
    return snapshot.value.queued.find((entry) => entry.id === analysisId)
  }

  function guestBusy(guestName: string): boolean {
    const onGuest = (analysis: { guest: string | null }) => analysis.guest === guestName
    return running.value.some(onGuest) || snapshot.value.queued.some(onGuest)
  }

  const unsubscribe = system.onQueue(applyPush)
  void load()

  onScopeDispose(unsubscribe)

  return { running, runningCount, queuedCount, queuedEntryOf, guestBusy }
})
