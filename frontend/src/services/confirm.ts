import { Dialog } from 'quasar'
import { t } from '@/i18n'

export interface ConfirmOptions {
  title: string
  message: string
  confirmLabel?: string
}

/**
 * Asks before something that cannot be undone. Resolves true only on an explicit confirm: cancel,
 * Escape and any other way of closing the dialog all count as "no".
 */
export function confirmDestructive({ title, message, confirmLabel = t('common.delete') }: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    Dialog.create({
      title,
      message,
      dark: true,
      // Clicking next to a destructive prompt must never answer it.
      persistent: true,
      cancel: { label: t('common.cancel'), flat: true, square: true, color: 'grey' },
      ok: { label: confirmLabel, outline: true, square: true, color: 'negative' },
    })
      .onOk(() => resolve(true))
      .onCancel(() => resolve(false))
      .onDismiss(() => resolve(false))
  })
}
