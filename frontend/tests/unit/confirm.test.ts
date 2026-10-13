import { Dialog } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { confirmDestructive } from '@/services/confirm'

type Callback = () => void
type DialogOptions = { ok: { label: string; color: string } } & Record<string, unknown>

function stubDialog() {
  const callbacks: Record<'ok' | 'cancel' | 'dismiss', Callback> = {
    ok: () => undefined,
    cancel: () => undefined,
    dismiss: () => undefined,
  }
  const chain = {
    onOk(callback: Callback) {
      callbacks.ok = callback
      return chain
    },
    onCancel(callback: Callback) {
      callbacks.cancel = callback
      return chain
    },
    onDismiss(callback: Callback) {
      callbacks.dismiss = callback
      return chain
    },
  }
  const create = vi.fn<(options: DialogOptions) => typeof chain>(() => chain)
  // Quasar attaches `Dialog.create` only once its plugin is installed into a mounted app.
  Dialog.create = create as unknown as typeof Dialog.create
  return { create, callbacks }
}

describe('confirmDestructive', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('keeps the cancel button neutral so only the destructive action carries a colour', () => {
    const { create } = stubDialog()
    void confirmDestructive({ title: 'Delete #4', message: 'This cannot be undone.' })

    const options = create.mock.calls[0]![0]
    expect(options.cancel).toMatchObject({ color: 'grey' })
  })

  it('resolves true when the user confirms', async () => {
    const { callbacks } = stubDialog()
    const answer = confirmDestructive({ title: 'Delete #4', message: 'This cannot be undone.' })

    callbacks.ok()
    callbacks.dismiss()

    await expect(answer).resolves.toBe(true)
  })

  it('resolves false when the user cancels', async () => {
    const { callbacks } = stubDialog()
    const answer = confirmDestructive({ title: 'Delete #4', message: 'This cannot be undone.' })

    callbacks.cancel()
    callbacks.dismiss()

    await expect(answer).resolves.toBe(false)
  })

  it('resolves false when the dialog is dismissed without an answer', async () => {
    const { callbacks } = stubDialog()
    const answer = confirmDestructive({ title: 'Delete #4', message: 'This cannot be undone.' })

    callbacks.dismiss()

    await expect(answer).resolves.toBe(false)
  })

  it('shows the title and message, and cannot be dismissed by clicking outside', () => {
    const { create } = stubDialog()

    void confirmDestructive({ title: 'Delete #4', message: 'This removes its CAPE task.' })

    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Delete #4',
        message: 'This removes its CAPE task.',
        persistent: true,
      }),
    )
  })

  it('labels the confirm button DELETE unless told otherwise, and styles it as destructive', () => {
    const { create } = stubDialog()

    void confirmDestructive({ title: 't', message: 'm' })
    void confirmDestructive({ title: 't', message: 'm', confirmLabel: 'REMOVE' })

    const [first, second] = create.mock.calls.map(([options]) => options)
    expect(first?.ok).toMatchObject({ label: 'DELETE', color: 'negative' })
    expect(second?.ok.label).toBe('REMOVE')
  })
})
