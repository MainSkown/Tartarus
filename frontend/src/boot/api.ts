import { defineBoot } from '#q-app'
import { Notify } from 'quasar'
import { client } from '@/api/client.gen'
import type { ErrorEnvelope } from '@/api'

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

function fieldMessages(details: unknown): string[] {
  if (typeof details !== 'object' || details === null) return []
  const fields = (details as { fields?: unknown }).fields
  if (!Array.isArray(fields)) return []
  return fields
    .map((field) => (typeof field === 'object' && field !== null ? (field as Record<string, unknown>).message : undefined))
    .filter((message): message is string => typeof message === 'string')
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

  const captions = fieldMessages(error.error.details)
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
