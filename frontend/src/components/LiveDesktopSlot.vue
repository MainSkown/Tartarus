<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AnalysisRead } from '@/api'
import DesktopMessage from '@/components/DesktopMessage.vue'
import DesktopToolbar from '@/components/DesktopToolbar.vue'
import PaneHeading from '@/components/PaneHeading.vue'
import { useDesktopSession } from '@/composables/use-desktop-session'
import { useFullscreen } from '@/composables/use-fullscreen'
import { useLastScreenshot } from '@/composables/use-last-screenshot'
import { isTerminalStatus } from '@/services/analysis-status'
import { hasDesktop } from '@/services/desktop-close'
import { screenshotUrl } from '@/services/screenshot-url'

const props = defineProps<{ analysis: AnalysisRead }>()

const root = ref<HTMLElement>()
const screen = ref<HTMLElement>()
const stage = ref<HTMLElement>()

const desktop = useDesktopSession({
  analysisId: () => props.analysis.id,
  wanted: () => hasDesktop(props.analysis.status),
  screen,
  stage,
})
const fullscreen = useFullscreen(root)
const { last } = useLastScreenshot(
  () => props.analysis.id,
  () => props.analysis.status,
)

const connected = computed(() => desktop.phase.value === 'connected')
const lastScreenshot = computed(() =>
  isTerminalStatus(props.analysis.status) && last.value > 0 ? screenshotUrl(props.analysis.id, last.value) : undefined,
)

function focusScreen(): void {
  screen.value?.focus({ preventScroll: true })
}

function keepKeysFromTheApp(event: KeyboardEvent): void {
  if (desktop.capturing.value) event.stopPropagation()
}
</script>

<template>
  <section
    ref="root"
    class="live-desktop"
    data-live="desktop"
  >
    <PaneHeading label="DESKTOP" />
    <div
      ref="screen"
      class="live-desktop__screen"
      :class="{ 'live-desktop__screen--captured': desktop.capturing.value }"
      :data-captured="String(desktop.capturing.value)"
      data-desktop="screen"
      tabindex="0"
      @focus="desktop.focus"
      @blur="desktop.blur"
      @mousedown.capture="focusScreen"
      @contextmenu.prevent
      @keydown="keepKeysFromTheApp"
      @keyup="keepKeysFromTheApp"
    >
      <div
        ref="stage"
        class="live-desktop__stage"
        :class="{ 'live-desktop__stage--waiting': !connected }"
      />
      <DesktopMessage
        v-if="!connected"
        :phase="desktop.phase.value"
        :reason="desktop.reason.value"
        :screenshot="lastScreenshot"
        @retry="desktop.connect"
      />
    </div>
    <DesktopToolbar
      :live="connected"
      :fullscreen="fullscreen.active.value"
      :capturing="desktop.capturing.value"
      :note="fullscreen.error.value"
      @fullscreen="fullscreen.toggle"
      @ctrl-alt-del="desktop.sendCtrlAltDel"
    />
  </section>
</template>

<style scoped>
.live-desktop {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: var(--spacing-xs) var(--spacing-sm) var(--spacing-sm);
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
}

.live-desktop__screen {
  position: relative;
  flex: 1 1 0;
  min-width: 0;
  min-height: 8rem;
  border: 2px solid var(--border-primary);
  background: var(--black);
  outline: none;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.live-desktop__screen--captured {
  border-color: var(--blue-primary);
  box-shadow: var(--shadow-blue-medium);
}

/* Stacked under the other panels there is no height to fill, so the screen takes the guest's own proportions. */
@media (max-width: 900px) {
  .live-desktop__screen {
    flex: none;
    aspect-ratio: 16 / 10;
  }
}

/* Hidden, not removed: the stage keeps its size, so the display is fitted before the first frame shows. */
.live-desktop__stage--waiting {
  visibility: hidden;
}

.live-desktop__stage {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
</style>
