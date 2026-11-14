import { computed, readonly, ref, watch, type ComputedRef, type Ref } from 'vue'
import { guestsPassword } from '@/api'
import { errorMessage } from '@/services/api-error'
import { quietOn } from '@/services/quiet-statuses'

// The card shows these where the analyst pressed, so a toast on top would only repeat them.
const FAILURES_SHOWN_ON_CARD = quietOn(404, 502, 503, 504)

export interface GuestPassword {
  /** The password while it is revealed; never kept otherwise. */
  value: Readonly<Ref<string | undefined>>
  revealed: ComputedRef<boolean>
  /** A request is in flight, for a reveal or a copy: no second one starts. */
  busy: Readonly<Ref<boolean>>
  /** The request in flight is a reveal, which the reveal control shows. */
  revealing: Readonly<Ref<boolean>>
  error: Readonly<Ref<string | undefined>>
  toggle: () => Promise<void>
  /** The password to put on the clipboard: the revealed one, or one fetched and not kept. Nothing when the fetch failed (`error` says why) or one is in flight. */
  valueToCopy: () => Promise<string | undefined>
}

/** A guest's account password, fetched only when the analyst asks to see or copy it and forgotten when hidden: the guest list never carries it. */
export function useGuestPassword(guestName: () => string): GuestPassword {
  const value = ref<string>()
  const busy = ref(false)
  const revealing = ref(false)
  const error = ref<string>()

  async function fetchPassword(): Promise<string | undefined> {
    error.value = undefined
    busy.value = true
    try {
      const { data, error: failure } = await guestsPassword({ path: { name: guestName() }, meta: FAILURES_SHOWN_ON_CARD })
      if (data && !failure) return data.password
      error.value = errorMessage(failure)
      return undefined
    } finally {
      busy.value = false
    }
  }

  async function toggle(): Promise<void> {
    if (busy.value) return
    if (value.value !== undefined) {
      value.value = undefined
      return
    }
    revealing.value = true
    try {
      value.value = await fetchPassword()
    } finally {
      revealing.value = false
    }
  }

  async function valueToCopy(): Promise<string | undefined> {
    if (value.value !== undefined) return value.value
    if (busy.value) return undefined
    return fetchPassword()
  }

  watch(guestName, () => {
    value.value = undefined
  })

  return { value: readonly(value), revealed: computed(() => value.value !== undefined), busy: readonly(busy), revealing: readonly(revealing), error: readonly(error), toggle, valueToCopy }
}
