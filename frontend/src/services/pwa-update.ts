import { Notify } from 'quasar'
import { t } from '@/i18n'

let announced = false

/**
 * A new build is installed in the background while the old one is still on the screen, so it
 * would otherwise show up only after a second reload. Reloading by itself could tear down a
 * live run or a desktop session, so the user is asked.
 */
export function announceUpdate(reload: () => void = () => window.location.reload()): void {
  if (announced) return
  announced = true
  Notify.create({
    type: 'tt-info',
    message: t('shell.update.ready'),
    timeout: 0,
    actions: [{ label: t('shell.update.reload'), handler: reload }],
  })
}
