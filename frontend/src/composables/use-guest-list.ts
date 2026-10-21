import { computed, onScopeDispose, ref, watch, type ComputedRef } from 'vue'
import { Notify } from 'quasar'
import { guestsActiveBuild, guestsCheck, guestsDelete, guestsReadBuild, guestsRetrySelftest, settingsRead } from '@/api'
import type { BuildView, Guest, GuestProfile, HealthCheckResult } from '@/api'
import { t } from '@/i18n'
import { errorMessage } from '@/services/api-error'
import { confirmDestructive } from '@/services/confirm'
import { isInProgress } from '@/services/guest-state'
import { guestDeleteConfirmation } from '@/services/guest-view'
import { quietOn } from '@/services/quiet-statuses'
import { useGuestsStore } from '@/stores/guests'
import { useSystemStore } from '@/stores/system'

export const POLL_INTERVAL_MS = 5_000

const GUEST_BUILD_JOB = 'guest_build'
// These are shown on the card the analyst pressed, so a toast on top would only repeat them.
const REFUSAL_STATUSES = quietOn(409, 502, 503, 504)

export interface CheckState {
  busy: boolean
  result?: HealthCheckResult
  error?: string
}

export interface GuestList {
  guests: ComputedRef<Guest[]>
  /** True until the first answer, whether it listed guests or failed. */
  loading: ComputedRef<boolean>
  loadError: ComputedRef<string | undefined>
  defaultName: ComputedRef<string | undefined>
  profileOf: (guest: Guest) => GuestProfile | undefined
  editionOf: (guest: Guest) => string | undefined
  buildOf: (name: string) => BuildView | undefined
  checkOf: (name: string) => CheckState | undefined
  isDeleting: (name: string) => boolean
  deleteErrorOf: (name: string) => string | undefined
  isRetesting: (name: string) => boolean
  retestErrorOf: (name: string) => string | undefined
  reload: () => Promise<void>
  runChecks: (name: string) => Promise<void>
  remove: (name: string) => Promise<void>
  retestSelfTest: (name: string) => Promise<void>
}

/** What the Guest page shows and does: the guests kept fresh, with each one's build progress, checks, delete and self-test retry. */
export function useGuestList(): GuestList {
  const store = useGuestsStore()
  const system = useSystemStore()

  const loadedOnce = ref(false)
  const defaultSetting = ref<string | null>()
  const builds = ref<Record<string, BuildView>>({})
  const checks = ref<Record<string, CheckState>>({})
  const deleting = ref<Record<string, boolean>>({})
  const deleteErrors = ref<Record<string, string>>({})
  const retesting = ref<Record<string, boolean>>({})
  const retestErrors = ref<Record<string, string>>({})

  const anyInProgress = computed(() => store.guests.some((guest) => isInProgress(guest.state)))
  const defaultName = computed(() => store.defaultGuestName(defaultSetting.value))

  let reloading = false
  let reloadQueued = false
  let pollTimer: ReturnType<typeof setInterval> | undefined

  async function readDefaultSetting(): Promise<void> {
    const { data } = await settingsRead({ meta: quietOn(500, 502, 503, 504) })
    defaultSetting.value = data?.default_guest
  }

  async function activeBuild() {
    const { data } = await guestsActiveBuild({ meta: quietOn(404, 502, 503, 504) })
    return data
  }

  async function refreshBuilds(): Promise<void> {
    const building = store.guests.filter((guest) => isInProgress(guest.state))
    const active = building.some((guest) => !guest.build_id) ? await activeBuild() : undefined
    const progress: Record<string, BuildView> = {}
    await Promise.all(
      building.map(async (guest) => {
        const buildId = guest.build_id ?? (active?.guest === guest.name ? active.build_id : undefined)
        if (!buildId) return
        const { data } = await guestsReadBuild({ path: { build_id: buildId }, meta: quietOn(404, 502, 503, 504) })
        if (data) progress[guest.name] = data
      }),
    )
    builds.value = progress
  }

  async function refresh(): Promise<void> {
    await store.load()
    await refreshBuilds()
    loadedOnce.value = true
  }

  // A job message and a poll tick can land together; one reload in flight plus one queued is all they need.
  async function reload(): Promise<void> {
    if (reloading) {
      reloadQueued = true
      return
    }
    reloading = true
    try {
      do {
        reloadQueued = false
        await refresh()
      } while (reloadQueued)
    } finally {
      reloading = false
    }
  }

  async function runChecks(name: string): Promise<void> {
    if (checks.value[name]?.busy) return
    checks.value[name] = { busy: true }
    const { data, error } = await guestsCheck({ path: { name }, meta: REFUSAL_STATUSES })
    checks.value[name] = data && !error ? { busy: false, result: data } : { busy: false, error: errorMessage(error) }
  }

  async function remove(name: string): Promise<void> {
    if (!(await confirmDestructive(guestDeleteConfirmation(name)))) return
    delete deleteErrors.value[name]
    deleting.value[name] = true
    const { error } = await guestsDelete({ path: { name }, meta: REFUSAL_STATUSES })
    deleting.value[name] = false
    if (error) {
      deleteErrors.value[name] = errorMessage(error)
      return
    }
    Notify.create({ type: 'tt-success', message: t('guests.delete.deleted', { name }) })
    await reload()
  }

  async function retestSelfTest(name: string): Promise<void> {
    if (retesting.value[name]) return
    delete retestErrors.value[name]
    retesting.value[name] = true
    const { error } = await guestsRetrySelftest({ path: { name }, meta: REFUSAL_STATUSES })
    retesting.value[name] = false
    if (error) {
      retestErrors.value[name] = errorMessage(error)
      return
    }
    await reload()
  }

  watch(
    anyInProgress,
    (building) => {
      clearInterval(pollTimer)
      pollTimer = building ? setInterval(() => void reload(), POLL_INTERVAL_MS) : undefined
    },
    { immediate: true },
  )
  const stopListening = system.onJob((job) => {
    if (job.type === GUEST_BUILD_JOB) void reload()
  })
  onScopeDispose(() => {
    clearInterval(pollTimer)
    stopListening()
  })

  void store.loadProfiles()
  void store.loadMedia()
  void readDefaultSetting()
  void reload()

  return {
    guests: computed(() => store.guests),
    loading: computed(() => !loadedOnce.value),
    loadError: computed(() => store.loadError),
    defaultName,
    profileOf: (guest) => store.profiles.find((profile) => profile.id === guest.profile),
    editionOf: (guest) => store.editionName(guest),
    buildOf: (name) => builds.value[name],
    checkOf: (name) => checks.value[name],
    isDeleting: (name) => deleting.value[name] === true,
    deleteErrorOf: (name) => deleteErrors.value[name],
    isRetesting: (name) => retesting.value[name] === true,
    retestErrorOf: (name) => retestErrors.value[name],
    reload,
    runChecks,
    remove,
    retestSelfTest,
  }
}
