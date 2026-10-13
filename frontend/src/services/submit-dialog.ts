import { Dialog } from 'quasar'
import SubmitDialog from '@/components/SubmitDialog.vue'

export function openSubmitDialog(): void {
  Dialog.create({ component: SubmitDialog })
}
