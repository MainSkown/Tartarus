import { errorMessage } from '@/services/api-error'

export interface ValidationIssue {
  // Last segment of the 422 `location` (e.g. "disk_warn_gb" for ["body", "disk_warn_gb"]),
  // empty when the server gave no usable location.
  field: string
  message: string
}

interface RawIssue {
  location?: unknown
  message?: unknown
}

function isIssue(value: ValidationIssue | undefined): value is ValidationIssue {
  return value !== undefined
}

function toIssue(raw: unknown): ValidationIssue | undefined {
  if (typeof raw !== 'object' || raw === null) return undefined
  const { location, message } = raw as RawIssue
  if (typeof message !== 'string') return undefined
  const last = Array.isArray(location) ? location.at(-1) : undefined
  return { field: typeof last === 'string' ? last : '', message }
}

/**
 * Reads the per-field issues out of a `{error: {details: {fields: [...]}}}` envelope (the
 * backend spec's 422 shape). Anything else yields no issues, so callers fall back to the
 * global error toast.
 */
export function validationIssues(error: unknown): ValidationIssue[] {
  const fields = (error as { error?: { details?: { fields?: unknown } } } | undefined)?.error?.details?.fields
  if (!Array.isArray(fields)) return []
  return fields.map(toIssue).filter(isIssue)
}

/** The first per-field message of a 422, else the envelope's own message: one line to show beside what was refused. */
export function refusalMessage(error: unknown): string {
  return validationIssues(error)[0]?.message ?? errorMessage(error)
}
