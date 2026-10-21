import { computed, ref, watch, type ComputedRef, type Ref, type WritableComputedRef } from 'vue'
import type { Guest } from '@/api'
import { t } from '@/i18n'
import { useGuestsStore } from '@/stores/guests'
import { useQueueStore } from '@/stores/queue'

export const AUTO_PACKAGE = 'auto'
// Used only while the profiles are unavailable; the gui spec names these as the usual CAPE packages.
export const FALLBACK_PACKAGES = ['exe', 'dll', 'doc', 'xls', 'ps1', 'js']

export interface GuestOption {
  name: string
  badges: string[]
  profileName?: string
  ramMb?: number
  disabled: boolean
  /** The guest's state, when that is what keeps it from being chosen. */
  reason?: string
  /** It runs an analysis or has one queued, so a submission waits behind it. */
  busy?: boolean
}

export interface GuestChoice {
  guestName: WritableComputedRef<string | undefined>
  guestOptions: ComputedRef<GuestOption[]>
  chosenOption: ComputedRef<GuestOption | undefined>
  packageName: Ref<string>
  packageOptions: ComputedRef<string[]>
  noGuestReason: ComputedRef<string | undefined>
  listUnavailable: ComputedRef<boolean>
  optionPayload: ComputedRef<{ guest?: string; package?: string }>
  load: () => Promise<void>
}

/**
 * The Submit dialog's GUEST and PACKAGE controls: which guest is chosen (the analyst's pick, else the
 * Settings default, else the first ready guest), which of them can be chosen, and the package that guest accepts.
 */
export function useGuestChoice(defaultGuest: Ref<string | null | undefined>): GuestChoice {
  const store = useGuestsStore()
  const queue = useQueueStore()
  const listLoaded = ref(false)
  const picked = ref<string>()
  const packageName = ref(AUTO_PACKAGE)

  const guestName = computed<string | undefined>({
    get: () => {
      const pickedStillReady = picked.value && store.readyGuests.some((guest) => guest.name === picked.value)
      return pickedStillReady ? picked.value : store.defaultGuestName(defaultGuest.value)
    },
    set: (name) => {
      picked.value = name
    },
  })

  function profileNameOf(guest: Guest): string | undefined {
    return store.profiles.find((profile) => profile.id === guest.profile)?.display_name
  }

  const guestOptions = computed<GuestOption[]>(() =>
    store.guests.map((guest) => {
      const ready = guest.state === 'ready'
      return {
        name: guest.name,
        badges: guest.badges ?? [],
        profileName: profileNameOf(guest),
        ramMb: guest.resources?.ram_mb,
        disabled: !ready,
        reason: ready ? undefined : guest.state,
        busy: queue.guestBusy(guest.name),
      }
    }),
  )

  const chosenOption = computed(() => guestOptions.value.find((option) => option.name === guestName.value))

  const packageOptions = computed(() => {
    const profilesLoaded = store.profiles.length > 0
    const accepted = profilesLoaded ? store.packagesOf(guestName.value ?? '') : FALLBACK_PACKAGES
    return [AUTO_PACKAGE, ...accepted]
  })

  watch(packageOptions, (options) => {
    if (!options.includes(packageName.value)) packageName.value = AUTO_PACKAGE
  })

  const listUnavailable = computed(() => listLoaded.value && store.loadError !== undefined)

  const noGuestReason = computed(() => {
    if (!listLoaded.value || listUnavailable.value || store.readyGuests.length > 0) return undefined
    if (store.guests.length === 0) return t('guests.choice.noneBuilt')
    const states = store.guests.map((guest) => t('guests.choice.stateOf', { name: guest.name, state: guest.state }))
    return t('guests.choice.noneReady', { states: states.join(', ') })
  })

  const optionPayload = computed(() => ({
    ...(guestName.value ? { guest: guestName.value } : {}),
    ...(packageName.value !== AUTO_PACKAGE ? { package: packageName.value } : {}),
  }))

  async function load(): Promise<void> {
    await Promise.all([store.load(), store.loadProfiles()])
    listLoaded.value = true
  }

  return { guestName, guestOptions, chosenOption, packageName, packageOptions, noGuestReason, listUnavailable, optionPayload, load }
}
