import { defineBoot } from '#q-app'
import { Notify } from 'quasar'
import { client } from '@/api/client.gen'
import type { ErrorEnvelope } from '@/api'
import { genericErrorMessage } from '@/services/api-error'
import { isQuietFailure } from '@/services/quiet-statuses'
import { validationIssues } from '@/services/validation-errors'

// Empty, not '/api': every generated URL in sdk.gen.ts already starts with /api (the backend
// mounts its router at APIRouter(prefix="/api")), so a '/api' base would send /api/api/...
// Same-origin works because the Vite dev server and production nginx both proxy /api.
const API_BASE_URL = ''

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== 'object' || value === null) return false
  const error = (value as { error?: unknown }).error
  if (typeof error !== 'object' || error === null) return false
  const body = error as Record<string, unknown>
  return typeof body.code === 'string' && typeof body.message === 'string'
}

/**
 * Turns a `{error: {code, message, details}}` envelope (or any other error shape a non-2xx
 * response or a raw network failure can produce) into a `tt-error` toast.
 */
export function notifyApiError(error: unknown): void {
  if (!isErrorEnvelope(error)) {
    Notify.create({ type: 'tt-error', message: genericErrorMessage() })
    return
  }

  const captions = validationIssues(error).map((issue) => issue.message)
  Notify.create({
    type: 'tt-error',
    message: error.error.message,
    ...(captions.length > 0 ? { caption: captions.join('\n') } : {}),
  })
}

export default defineBoot(() => {
  client.setConfig({ baseUrl: API_BASE_URL })
  client.interceptors.error.use((error, response, _request, options) => {
    // The generated client hands interceptors the caller's own options, `meta` included, but types them without it.
    const { meta } = options as { meta?: Record<string, unknown> }
    if (!isQuietFailure(response, meta)) notifyApiError(error)
    return error
  })
})
