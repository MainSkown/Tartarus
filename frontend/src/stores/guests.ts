import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { guestsList, guestsMedia, guestsProfiles } from '@/api'
import type { Guest, GuestProfile, MediaEntry } from '@/api'
import { errorMessage } from '@/services/api-error'
import { quietOn } from '@/services/quiet-statuses'

/**
 * The guests the analyst can detonate on and the OS profiles they were built from. The Submit
 * dialog, the Settings default and the Guest page all read this one list.
 */
export const useGuestsStore = defineStore('guests', () => {
  const guests = ref<Guest[]>([])
  const profiles = ref<GuestProfile[]>([])
  const media = ref<MediaEntry[]>([])
  const loadError = ref<string>()

  const readyGuests = computed(() => guests.value.filter((guest) => guest.state === 'ready'))

  async function load(): Promise<void> {
    // The Submit button already says when guests are unavailable; a toast on top would only repeat it.
    const { data, error } = await guestsList({ meta: quietOn(502) })
    loadError.value = error || !data ? errorMessage(error) : undefined
    if (data && !error) guests.value = data
  }

  async function loadProfiles(): Promise<void> {
    const { data, error } = await guestsProfiles({ meta: quietOn(502) })
    if (data && !error) profiles.value = data
  }

  async function loadMedia(): Promise<void> {
    const { data, error } = await guestsMedia({ meta: quietOn(502) })
    if (data && !error) media.value = data
  }

  /** The edition a guest was built from ("Windows 11 Pro"): its record keeps only the index, the media names it. */
  function editionName(guest: Guest): string | undefined {
    const built = guest.media
    if (!built?.variant) return undefined
    const entry = media.value.find((candidate) => candidate.file === built.file)
    return entry?.variants?.find((variant) => String(variant.index) === built.variant)?.name
  }

  function byName(name: string): Guest | undefined {
    return guests.value.find((guest) => guest.name === name)
  }

  /** The Settings default if that guest is ready, else the first ready one. */
  function defaultGuestName(setting: string | null | undefined): string | undefined {
    if (setting && readyGuests.value.some((guest) => guest.name === setting)) return setting
    return readyGuests.value[0]?.name
  }

  function packagesOf(name: string): string[] {
    const profileId = byName(name)?.profile
    return profiles.value.find((profile) => profile.id === profileId)?.packages ?? []
  }

  return { guests, profiles, media, loadError, readyGuests, load, loadProfiles, loadMedia, editionName, byName, defaultGuestName, packagesOf }
})
