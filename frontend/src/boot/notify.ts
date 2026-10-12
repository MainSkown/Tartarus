import { defineBoot } from '#q-app'
import { Notify, type QNotifyOptions } from 'quasar'

const base: QNotifyOptions = {
  position: 'bottom-right',
  timeout: 5000,
  progress: true,
  actions: [{ icon: 'close', color: 'grey', round: true, flat: true }],
}

export default defineBoot(() => {
  Notify.registerType('tt-info', { ...base, icon: 'info', classes: 'tt-toast tt-toast--info' })
  Notify.registerType('tt-success', { ...base, icon: 'check_circle', classes: 'tt-toast tt-toast--success' })
  Notify.registerType('tt-warning', { ...base, icon: 'report', classes: 'tt-toast tt-toast--warning' })
  // Errors must be read, so they stay until dismissed.
  Notify.registerType('tt-error', { ...base, icon: 'dangerous', classes: 'tt-toast tt-toast--error', timeout: 0 })
})
