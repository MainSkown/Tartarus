import { ref } from 'vue'
import { Notify } from 'quasar'
import type { ExportFormat } from '@/api'
import { downloadIocs, iocFormat } from '@/services/ioc-export'

/** IOC downloads one at a time, with the format in flight exposed for the menu's feedback. */
export function useIocExport() {
  const downloading = ref<ExportFormat>()

  async function download(analysisId: number, format: ExportFormat): Promise<void> {
    if (downloading.value) return
    downloading.value = format
    const label = iocFormat(format).label
    const dismissPreparing = Notify.create({
      type: 'tt-info',
      spinner: true,
      message: `Preparing the ${label} IOCs…`,
      timeout: 0,
    })
    const saved = await downloadIocs(analysisId, format).finally(() => {
      dismissPreparing()
      downloading.value = undefined
    })
    // A failure was already toasted by the API interceptor with the server's message.
    if (saved) Notify.create({ type: 'tt-success', message: `${label} IOCs downloaded` })
  }

  return { downloading, download }
}
