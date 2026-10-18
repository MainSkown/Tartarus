<script setup lang="ts">
import { computed } from 'vue'
import { t } from '@/i18n'

const props = defineProps<{ live: boolean; fullscreen: boolean; capturing: boolean; note?: string }>()
const emit = defineEmits<{ fullscreen: []; 'ctrl-alt-del': [] }>()

const hint = computed(() => {
  if (props.capturing) return t('live.desktop.toolbar.escToRelease')
  return props.live ? t('live.desktop.toolbar.clickToType') : ''
})
</script>

<template>
  <div class="desktop-toolbar text-mono">
    <q-btn
      outline
      square
      dense
      no-caps
      icon="fullscreen"
      :label="fullscreen ? t('live.desktop.toolbar.exitFullscreen') : t('live.desktop.toolbar.fullscreen')"
      class="desktop-toolbar__button"
      data-desktop="fullscreen"
      @click="emit('fullscreen')"
    />
    <q-btn
      outline
      square
      dense
      no-caps
      icon="keyboard"
      :label="t('live.desktop.toolbar.ctrlAltDel')"
      class="desktop-toolbar__button"
      data-desktop="ctrl-alt-del"
      :disable="!live"
      @click="emit('ctrl-alt-del')"
    />
    <span
      class="desktop-toolbar__note"
      :class="{ 'desktop-toolbar__note--active': capturing && !note, 'desktop-toolbar__note--wrap': note }"
      data-desktop="toolbar-note"
    >{{ note ?? hint }}</span>
  </div>
</template>

<style scoped>
.desktop-toolbar {
  display: flex;
  flex: none;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-xs) var(--spacing-sm);
  min-width: 0;
  padding-top: var(--spacing-xs);
}

.desktop-toolbar__button {
  color: var(--blue-primary);
  font-size: 0.7rem;
}

/* One line, so that taking or losing the keyboard never changes the height of the screen above. */
.desktop-toolbar__note {
  flex: 1 1 8rem;
  min-width: 0;
  overflow: hidden;
  color: var(--text-gray-dark);
  font-size: 0.7rem;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.desktop-toolbar__note--wrap {
  white-space: normal;
  overflow-wrap: anywhere;
}

.desktop-toolbar__note--active {
  color: var(--blue-primary);
}
</style>
