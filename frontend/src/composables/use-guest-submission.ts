import { ref, type Ref } from 'vue'
import { useRouter } from 'vue-router'
import type { BuildStarted } from '@/api'
import { errorMessage } from '@/services/api-error'
import { validationIssues } from '@/services/validation-errors'

export interface StartResult {
  data?: BuildStarted
  error?: unknown
}

export interface GuestSubmission {
  submitting: Ref<boolean>
  /** The server's message for each form field it refused, keyed by the field's dotted path (`identity.machine`). */
  fieldErrors: Ref<Record<string, string>>
  /** What the form cannot place on an input: a conflict, a refusal of a field the form has no input for, or an unreadable answer. */
  banner: Ref<string | undefined>
  /** Sends the request; resolves with the fields the server refused that the form has an input for, in the server's order. */
  submit: (send: () => Promise<StartResult>) => Promise<string[]>
  clearFieldError: (field: string) => void
}

/**
 * The part the build wizard and the clone form share: the busy flag, the mapping of a 409 or
 * a 422 onto the form, and the move to the build page once the backend has started the job.
 */
export function useGuestSubmission(hasInput: (field: string) => boolean): GuestSubmission {
  const router = useRouter()
  const submitting = ref(false)
  const fieldErrors = ref<Record<string, string>>({})
  const banner = ref<string>()

  function showRefusal(error: unknown): string[] {
    const issues = validationIssues(error)
    const placed = issues.filter((issue) => hasInput(issue.field))
    const unplaced = issues.filter((issue) => !hasInput(issue.field))
    for (const { field, message } of placed) fieldErrors.value[field] ??= message
    if (issues.length === 0) banner.value = errorMessage(error)
    else if (unplaced.length > 0) banner.value = unplaced.map(({ field, message }) => `${field} ${message}`).join('; ')
    return [...new Set(placed.map((issue) => issue.field))]
  }

  async function submit(send: () => Promise<StartResult>): Promise<string[]> {
    if (submitting.value) return []
    submitting.value = true
    fieldErrors.value = {}
    banner.value = undefined
    try {
      const { data, error } = await send()
      if (data && !error) {
        await router.push(`/guest/builds/${encodeURIComponent(data.build_id)}`)
        return []
      }
      return showRefusal(error)
    } finally {
      submitting.value = false
    }
  }

  function clearFieldError(field: string): void {
    delete fieldErrors.value[field]
  }

  return { submitting, fieldErrors, banner, submit, clearFieldError }
}
