import { computed, onBeforeUnmount, onMounted, ref, watch, type ComputedRef, type Ref } from 'vue'
import type { DesktopPhase } from '@/services/desktop-close'
import { loadGuacamole } from '@/services/desktop-guacamole'
import { DesktopSession } from '@/services/desktop-session'
import { resolveWsUrl } from '@/services/ws'

export interface DesktopSessionOptions {
  analysisId: () => number
  /** Whether the analysis is in a state that has a desktop; the connection follows it. */
  wanted: () => boolean
  /** The focusable element the keyboard listens on. */
  screen: Ref<HTMLElement | undefined>
  /** The empty element the guest's display is placed in. */
  stage: Ref<HTMLElement | undefined>
}

export interface DesktopSessionState {
  phase: Ref<DesktopPhase>
  reason: Ref<string>
  /** True while the guest receives the keyboard: the screen has focus and shows a picture. */
  capturing: ComputedRef<boolean>
  connect: () => Promise<void>
  focus: () => void
  blur: () => void
  sendCtrlAltDel: () => void
}

/** Owns the connection to the guest's desktop for as long as the component lives; the library is loaded on first use. */
export function useDesktopSession(options: DesktopSessionOptions): DesktopSessionState {
  const phase = ref<DesktopPhase>('not-running')
  const reason = ref('')
  const focused = ref(false)
  const capturing = computed(() => focused.value && phase.value === 'connected')
  let session: DesktopSession | undefined
  let attempt = 0
  let observer: ResizeObserver | undefined

  function fitToStage(): void {
    const stage = options.stage.value
    if (stage) session?.fit({ width: stage.clientWidth, height: stage.clientHeight })
  }

  function stop(): void {
    attempt += 1
    session?.disconnect()
    session = undefined
  }

  async function connect(): Promise<void> {
    stop()
    const mine = attempt
    phase.value = 'connecting'
    reason.value = ''
    try {
      const guacamole = await loadGuacamole()
      const { screen, stage } = options
      if (mine !== attempt || !screen.value || !stage.value) return
      session = new DesktopSession({
        guacamole,
        url: resolveWsUrl(`/ws/analyses/${options.analysisId()}/desktop`),
        panel: screen.value,
        stage: stage.value,
        onChange: (state) => {
          phase.value = state.phase
          reason.value = state.reason
        },
      })
      fitToStage()
      session.connect()
      if (focused.value) session.capture()
    } catch (failure) {
      if (mine !== attempt) return
      phase.value = 'failed'
      reason.value = failure instanceof Error ? failure.message : String(failure)
    }
  }

  function follow(wanted: boolean): void {
    if (wanted) {
      void connect()
    } else {
      stop()
      phase.value = 'not-running'
      reason.value = ''
    }
  }

  onMounted(() => {
    follow(options.wanted())
    if (typeof ResizeObserver !== 'undefined' && options.stage.value) {
      observer = new ResizeObserver(fitToStage)
      observer.observe(options.stage.value)
    }
  })
  watch(options.wanted, (wanted, was) => {
    if (wanted !== was) follow(wanted)
  })
  onBeforeUnmount(() => {
    observer?.disconnect()
    stop()
  })

  return {
    phase,
    reason,
    capturing,
    connect,
    focus: () => {
      focused.value = true
      session?.capture()
    },
    blur: () => {
      focused.value = false
      session?.release()
    },
    sendCtrlAltDel: () => session?.sendCtrlAltDel(),
  }
}
