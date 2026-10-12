import { Notify } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import configureApiClient, { notifyApiError } from '@/boot/api'
import { client } from '@/api/client.gen'
import type { ErrorEnvelope } from '@/api'

function registeredErrorInterceptor() {
  configureApiClient({} as Parameters<typeof configureApiClient>[0])
  const [interceptor] = client.interceptors.error.fns
  if (!interceptor) throw new Error('error interceptor was not registered')
  return interceptor
}

// Quasar only attaches `Notify.create` once its plugin is installed into a mounted app
// (see quasar/src/plugins/notify/Notify.js); outside that, the property doesn't exist yet,
// so vi.spyOn (which requires an existing property) can't be used here.
function mockNotifyCreate() {
  const notifyCreate = vi.fn()
  Notify.create = notifyCreate
  return notifyCreate
}

describe('api boot', () => {
  beforeEach(() => {
    client.interceptors.error.clear()
  })

  it('sets the base URL to the same-origin /api path', () => {
    configureApiClient({} as Parameters<typeof configureApiClient>[0])
    expect(client.getConfig().baseUrl).toBe('/api')
  })

  it('toasts the envelope message for a 404-shaped error', async () => {
    const notifyCreate = mockNotifyCreate()
    const interceptor = registeredErrorInterceptor()
    const envelope: ErrorEnvelope = {
      error: { code: 'not_found', message: 'Analysis not found', details: {} },
    }

    await interceptor(envelope, undefined, undefined, {} as never)

    expect(notifyCreate).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'tt-error', message: 'Analysis not found' }),
    )
  })

  it('includes field messages for a 422 validation error', async () => {
    const notifyCreate = mockNotifyCreate()
    const interceptor = registeredErrorInterceptor()
    const envelope: ErrorEnvelope = {
      error: {
        code: 'validation_error',
        message: 'Request validation failed',
        details: {
          fields: [
            { location: ['body', 'timeout'], message: 'Timeout must be >= 60', type: 'greater_than_equal' },
            { location: ['body', 'route'], message: 'Unknown route', type: 'value_error' },
          ],
        },
      },
    }

    await interceptor(envelope, undefined, undefined, {} as never)

    expect(notifyCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'tt-error',
        caption: 'Timeout must be >= 60\nUnknown route',
      }),
    )
  })

  it('falls back to a generic message for a malformed error body', async () => {
    const notifyCreate = mockNotifyCreate()
    const interceptor = registeredErrorInterceptor()

    expect(() => interceptor('<html>502 Bad Gateway</html>', undefined, undefined, {} as never)).not.toThrow()

    expect(notifyCreate).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'tt-error', message: expect.any(String) }),
    )
  })

  it('falls back to a generic message for a raw network failure with no response', async () => {
    const notifyCreate = mockNotifyCreate()
    const interceptor = registeredErrorInterceptor()

    expect(() =>
      interceptor(new TypeError('Failed to fetch'), undefined, undefined, {} as never),
    ).not.toThrow()

    expect(notifyCreate).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-error' }))
  })

  it('exposes notifyApiError directly for reuse without going through the client', () => {
    const notifyCreate = mockNotifyCreate()
    notifyApiError({ error: { code: 'conflict', message: 'Guest is not ready', details: {} } })
    expect(notifyCreate).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'tt-error', message: 'Guest is not ready' }),
    )
  })
})
