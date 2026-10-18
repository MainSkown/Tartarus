<script setup lang="ts">
import { computed, ref } from 'vue'
import { t } from '@/i18n'
import DesktopMessage from '@/components/DesktopMessage.vue'
import DesktopToolbar from '@/components/DesktopToolbar.vue'
import PaneHeading from '@/components/PaneHeading.vue'
import { useDesktopSession } from '@/composables/use-desktop-session'
import { useFullscreen } from '@/composables/use-fullscreen'
import type { DesktopPhase, DesktopSubject } from '@/services/desktop-close'

const props = defineProps<{
  /** The socket path of the desktop (`desktop-url.ts`). */
  path: string
  /** Whether what the desktop belongs to is in a state that has one; the connection follows it. */
  wanted: boolean
  subject?: DesktopSubject
  /** Turns the session's phase into what to say, when the owner knows more than the socket does. */
  adjustPhase?: (phase: DesktopPhase) => DesktopPhase
  /** The last picture of the guest, shown dimmed behind a message once the desktop is gone. */
  screenshot?: string
}>()

const root = ref<HTMLElement>()
const screen = ref<HTMLElement>()
const stage = ref<HTMLElement>()

const desktop = useDesktopSession({ path: () => props.path, wanted: () => props.wanted, screen, stage })
const fullscreen = useFullscreen(root)

const shownPhase = computed(() => props.adjustPhase?.(desktop.phase.value) ?? desktop.phase.value)
const connected = computed(() => desktop.phase.value === 'connected')

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
  >
    <PaneHeading :label="t('live.desktop.heading')" />
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
        :phase="shownPhase"
        :reason="desktop.reason.value"
        :screenshot="screenshot"
        :subject="subject"
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
