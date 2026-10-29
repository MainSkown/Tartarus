import { onScopeDispose, ref, watch, type Ref } from 'vue'
import { analysesArchiveMembers } from '@/api'
import type { ArchiveMemberRead } from '@/api'
import { errorMessage } from '@/services/api-error'
import { isZipFile } from '@/services/archive-file'
import { debounced } from '@/services/debounced'
import { quietOn } from '@/services/quiet-statuses'

const PASSWORD_PAUSE_MS = 400
// A 413 (over the sample size limit) is shown under the drop zone like a 422; the shared inline set does not include it.
const REFUSALS_SHOWN_UNDER_DROP_ZONE = quietOn(413, 422)

/**
 * The member list of the chosen file when it is a zip: asked of the backend when the file is chosen and
 * again, after a pause in typing, when the password changes. A reply to a question that has since been
 * replaced is dropped, and a file that is not a zip leaves nothing behind.
 */
export function useArchiveMembers(file: Readonly<Ref<File | undefined>>, password: Readonly<Ref<string>>) {
  const isArchive = ref(false)
  const members = ref<ArchiveMemberRead[]>([])
  const passwordOk = ref<boolean | null>()
  const loading = ref(false)
  const error = ref<string>()

  let latestQuestion = 0
  const askAgain = debounced(() => void ask(), PASSWORD_PAUSE_MS)

  function reset(): void {
    askAgain.cancel()
    latestQuestion++
    isArchive.value = false
    members.value = []
    passwordOk.value = undefined
    error.value = undefined
    loading.value = false
  }

  async function ask(): Promise<void> {
    const archive = file.value
    if (!archive) return
    const question = ++latestQuestion
    loading.value = true
    const { data, error: failure } = await analysesArchiveMembers({
      body: { file: archive, password: password.value },
      meta: REFUSALS_SHOWN_UNDER_DROP_ZONE,
    })
    if (question !== latestQuestion) return
    loading.value = false
    if (failure || !data) {
      members.value = []
      passwordOk.value = undefined
      error.value = errorMessage(failure)
      return
    }
    members.value = data.members
    passwordOk.value = data.password_ok
    error.value = undefined
  }

  watch(
    file,
    async (chosen) => {
      reset()
      if (!chosen) return
      const question = latestQuestion
      const zip = await isZipFile(chosen)
      if (question !== latestQuestion) return
      isArchive.value = zip
      if (zip) await ask()
    },
    { immediate: true },
  )

  watch(password, () => {
    if (!isArchive.value) return
    loading.value = true
    askAgain()
  })

  onScopeDispose(askAgain.cancel)

  return { isArchive, members, passwordOk, loading, error }
}
