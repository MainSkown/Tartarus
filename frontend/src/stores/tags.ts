import { defineStore } from 'pinia'
import { ref } from 'vue'
import { annotationsListTags } from '@/api'
import type { TagUsageRead } from '@/api'
import { errorMessage } from '@/services/api-error'
import { quietOn } from '@/services/quiet-statuses'

const MAX_SUGGESTIONS = 8

/** The tags in use across all analyses with their counts: what the tag inputs suggest and the Dashboard filters by. */
export const useTagsStore = defineStore('tags', () => {
  const items = ref<TagUsageRead[]>([])
  const loadError = ref<string>()

  async function load(): Promise<void> {
    // Suggestions are a convenience: when they cannot load, typing a tag still works.
    const { data, error } = await annotationsListTags({ meta: quietOn(500, 502, 504) })
    loadError.value = error || !data ? errorMessage(error) : undefined
    if (data && !error) items.value = data
  }

  function suggest(typed: string, leaveOut: string[] = []): TagUsageRead[] {
    const needle = typed.trim().toLowerCase()
    return items.value
      .filter((tag) => tag.name.includes(needle) && !leaveOut.includes(tag.name))
      .slice(0, MAX_SUGGESTIONS)
  }

  return { items, loadError, load, suggest }
})
