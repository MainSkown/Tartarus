import { readonly, shallowRef } from 'vue'
import { systemVersion, type VersionInfo } from '@/api'

export type AppVersionState =
  | { status: 'loading' }
  | { status: 'loaded'; info: VersionInfo }
  | { status: 'failed' }

/**
 * The release, commit and license the backend reports. `reload` asks again after a failure.
 */
export function useAppVersion() {
  const state = shallowRef<AppVersionState>({ status: 'loading' })

  async function reload(): Promise<void> {
    state.value = { status: 'loading' }
    try {
      const { data } = await systemVersion()
      state.value = data ? { status: 'loaded', info: data } : { status: 'failed' }
    } catch {
      state.value = { status: 'failed' }
    }
  }

  void reload()

  return { state: readonly(state), reload }
}
