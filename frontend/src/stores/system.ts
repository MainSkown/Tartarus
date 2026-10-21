import { defineStore } from 'pinia'
import { computed, onScopeDispose, ref } from 'vue'
import { systemHealth } from '@/api'
import type { HealthStatus, JobProgress, QueueSnapshot, SystemHealth } from '@/api'
import { createSystemClient } from '@/services/ws'

const STATUS_RANK: Record<HealthStatus, number> = { ok: 0, degraded: 1, down: 2 }

function worseStatus(a: HealthStatus, b: HealthStatus): HealthStatus {
  return STATUS_RANK[a] >= STATUS_RANK[b] ? a : b
}

/**
 * Holds the latest `/api/system/health` snapshot for the header's health dots and the
 * Submit button's disabled reason (gui spec "App shell"). `GET /api/system/health` populates
 * it immediately so the dots aren't blank on first paint; `/ws/system` then keeps it live
 * without further polling. The same socket carries the `job` and `queue` pushes: this store owns the one
 * connection and hands them to whoever registers with `onJob` or `onQueue`.
 */
export const useSystemStore = defineStore('system', () => {
  const health = ref<SystemHealth>()
  const wsClient = createSystemClient()
  const jobHandlers = new Set<(job: JobProgress) => void>()
  const queueHandlers = new Set<(snapshot: QueueSnapshot) => void>()

  function applyHealth(data: SystemHealth): void {
    health.value = data
  }

  function onJob(handler: (job: JobProgress) => void): () => void {
    jobHandlers.add(handler)
    return () => jobHandlers.delete(handler)
  }

  function onQueue(handler: (snapshot: QueueSnapshot) => void): () => void {
    queueHandlers.add(handler)
    return () => queueHandlers.delete(handler)
  }

  const unsubscribe = wsClient.subscribe((message) => {
    if (message.type === 'job') for (const handler of jobHandlers) handler(message.job)
    else if (message.type === 'queue') for (const handler of queueHandlers) handler(message.data)
    else applyHealth(message.data)
  })
  void systemHealth().then(({ data }) => {
    if (data) applyHealth(data)
  })
  wsClient.connect()

  // This store is a singleton for the app's lifetime, but Pinia still runs this inside a
  // disposable effect scope (store.$dispose(), HMR, or a fresh pinia per test) — without
  // this the WS socket and its reconnect timer would outlive the store that owns them.
  onScopeDispose(() => {
    unsubscribe()
    jobHandlers.clear()
    queueHandlers.clear()
    wsClient.disconnect()
  })

  const storeStatus = computed<HealthStatus | undefined>(() =>
    health.value ? worseStatus(health.value.postgres.status, health.value.opensearch.status) : undefined,
  )

  // degraded: some guest is not ready but at least one is, so a submission can still go somewhere.
  const guestReady = computed(() => health.value?.guest.status !== undefined && health.value.guest.status !== 'down')
  const guestMessage = computed(() => health.value?.guest.message ?? undefined)

  return {
    health,
    connectionState: wsClient.state,
    storeStatus,
    guestReady,
    guestMessage,
    onJob,
    onQueue,
  }
})
