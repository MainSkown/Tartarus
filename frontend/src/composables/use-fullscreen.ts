import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

/** Fullscreen for one element: whether it is active, and the browser's reason when it says no. */
export function useFullscreen(target: Ref<HTMLElement | undefined>): {
  active: Ref<boolean>
  error: Ref<string | undefined>
  toggle: () => Promise<void>
} {
  const active = ref(false)
  const error = ref<string>()

  function sync(): void {
    active.value = target.value !== undefined && document.fullscreenElement === target.value
  }

  async function toggle(): Promise<void> {
    error.value = undefined
    try {
      if (active.value) await document.exitFullscreen()
      else if (target.value?.requestFullscreen) await target.value.requestFullscreen()
      else throw new Error('this browser has no fullscreen support')
    } catch (failure) {
      error.value = `fullscreen was refused: ${failure instanceof Error ? failure.message : String(failure)}`
    }
  }

  onMounted(() => document.addEventListener('fullscreenchange', sync))
  onBeforeUnmount(() => document.removeEventListener('fullscreenchange', sync))

  return { active, error, toggle }
}
