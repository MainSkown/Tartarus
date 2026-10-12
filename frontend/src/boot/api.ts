import { defineBoot } from '#q-app'
import { Notify } from 'quasar'
import { client } from '@/api/client.gen'
import type { ErrorEnvelope } from '@/api'
import { validationIssues } from '@/services/validation-errors'

// Both the Vite dev server (quasar.config.ts devServer.proxy) and the production nginx
// container (see gui spec "Frontend structure") proxy /api to the backend, so the client
// never needs an absolute origin.
const API_BASE_URL = '/api'

const GENERIC_ERROR_MESSAGE = 'Something went wrong talking to the backend.'

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
    Notify.create({ type: 'tt-error', message: GENERIC_ERROR_MESSAGE })
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
  client.interceptors.error.use((error) => {
    notifyApiError(error)
    return error
  })
})
