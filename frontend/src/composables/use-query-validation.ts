import { onScopeDispose, ref, watch, type Ref } from 'vue'
import { queryValidate } from '@/api'
import type { QueryErrorRead } from '@/api'
import { QUIET_ON_QUERY_FAILURES } from '@/services/quiet-statuses'

export const VALIDATION_DELAY_MS = 250

export interface QueryValidation {
  /** The compiler's errors for the text last validated; empty while nothing is known. */
  errors: Ref<QueryErrorRead[]>
  /** The errors of the draft as it is now, asking at once if the answer is not in yet. */
  settle: () => Promise<QueryErrorRead[]>
}

async function ask(text: string): Promise<QueryErrorRead[]> {
  try {
    const { data } = await queryValidate({ body: { query: text }, meta: QUIET_ON_QUERY_FAILURES })
    return data?.errors ?? []
  } catch {
    // A failed request must neither show an error nor stop the query from being applied.
    return []
  }
}

/** Validates the draft after a pause in typing; an answer for a text that is no longer the draft is dropped. */
export function useQueryValidation(draft: Ref<string>): QueryValidation {
  const errors = ref<QueryErrorRead[]>([])
  let timer: ReturnType<typeof setTimeout> | undefined
  let requestedText = ''
  let inFlight: Promise<void> | undefined

  function validateNow(): Promise<void> {
    clearTimeout(timer)
    timer = undefined
    const text = draft.value
    requestedText = text
    if (text.trim() === '') {
      errors.value = []
      return Promise.resolve()
    }
    inFlight = ask(text).then((found) => {
      if (draft.value === text) errors.value = found
    })
    return inFlight
  }

  watch(draft, (text) => {
    clearTimeout(timer)
    if (text.trim() === '') {
      void validateNow()
      return
    }
    timer = setTimeout(() => void validateNow(), VALIDATION_DELAY_MS)
  }, { immediate: true })

  async function settle(): Promise<QueryErrorRead[]> {
    if (timer !== undefined || requestedText !== draft.value) await validateNow()
    else await inFlight
    return errors.value
  }

  onScopeDispose(() => clearTimeout(timer))
  return { errors, settle }
}
