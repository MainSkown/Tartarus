import { computed, ref, type Ref } from 'vue'
import { t } from '@/i18n'
import { useGuestsStore } from '@/stores/guests'

interface DefaultGuestOption {
  label: string
  value: string | null
}

/** The Settings DEFAULT GUEST select: the ready guests, and a note when the stored name will not be used. */
export function useDefaultGuestField(stored: Ref<string | null | undefined>) {
  const store = useGuestsStore()
  const judged = ref(false)

  const options = computed<DefaultGuestOption[]>(() => [
    { label: t('guests.defaultGuest.firstReady'), value: null },
    ...store.readyGuests.map((guest) => ({ label: guest.name, value: guest.name })),
  ])

  const storedIsOffered = computed(() => options.value.some((option) => option.value === stored.value))

  const note = computed(() => {
    const name = stored.value
    if (!judged.value || !name || storedIsOffered.value) return undefined
    const existing = store.byName(name)
    return existing
      ? t('guests.defaultGuest.stateNote', { name, state: existing.state })
      : t('guests.defaultGuest.gone', { name })
  })

  // Quasar would show nothing for a model value that matches no option.
  const displayValue = computed(() => (stored.value && !storedIsOffered.value ? stored.value : undefined))

  async function load(): Promise<void> {
    await store.load()
    judged.value = store.loadError === undefined
  }

  return { options, note, displayValue, load }
}
