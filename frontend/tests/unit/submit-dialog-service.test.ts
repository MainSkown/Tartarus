import { Dialog } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SubmitDialog from '@/components/SubmitDialog.vue'
import { openSubmitDialog } from '@/services/submit-dialog'

describe('openSubmitDialog', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('opens the Submit dialog component through the Dialog plugin', () => {
    // Quasar attaches `Dialog.create` only once its plugin is installed into a mounted app.
    const create = vi.fn()
    Dialog.create = create as unknown as typeof Dialog.create

    openSubmitDialog()

    expect(create).toHaveBeenCalledWith(expect.objectContaining({ component: SubmitDialog }))
  })
})
