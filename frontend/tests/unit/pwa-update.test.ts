import { Notify } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'

type ToastOptions = { type: string; message: string; timeout: number; actions: { label: string; handler: () => void }[] }

describe('announceUpdate', () => {
  let announceUpdate: (reload?: () => void) => void

  beforeEach(async () => {
    Notify.create = vi.fn()
    // The module remembers that it has announced, so every test starts from a fresh one.
    vi.resetModules()
    announceUpdate = (await import('@/services/pwa-update')).announceUpdate
  })

  const toast = (): ToastOptions => vi.mocked(Notify.create).mock.calls[0]![0] as unknown as ToastOptions

  it('tells the user a new version is ready, and keeps saying so until they act', () => {
    announceUpdate(vi.fn())
    expect(toast()).toMatchObject({ type: 'tt-info', timeout: 0 })
    expect(toast().message).toContain('new version')
  })

  it('reloads the page when the user asks for it', () => {
    const reload = vi.fn()
    announceUpdate(reload)
    toast().actions.find((action) => action.label === 'RELOAD')!.handler()
    expect(reload).toHaveBeenCalledOnce()
  })

  it('does not reload by itself: a live run or a desktop must not be torn down', () => {
    const reload = vi.fn()
    announceUpdate(reload)
    expect(reload).not.toHaveBeenCalled()
  })

  it('announces once, however often the browser reports the update', () => {
    announceUpdate(vi.fn())
    announceUpdate(vi.fn())
    expect(Notify.create).toHaveBeenCalledOnce()
  })
})
