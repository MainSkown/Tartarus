import { register } from 'register-service-worker'
import { announceUpdate } from '../src/services/pwa-update'

register(import.meta.env.QUASAR_SERVICE_WORKER_FILE, { updated: () => announceUpdate() })
