<script setup lang="ts">
import { t } from '@/i18n'

defineProps<{ live: boolean; fullscreen: boolean }>()
const emit = defineEmits<{ fullscreen: []; 'ctrl-alt-del': [] }>()
</script>

<template>
  <div class="desktop-toolbar text-mono">
    <q-btn
      flat
      dense
      square
      no-caps
      icon="fullscreen"
      :label="fullscreen ? t('live.desktop.toolbar.exitFullscreen') : t('live.desktop.toolbar.fullscreen')"
      class="desktop-toolbar__button"
      data-desktop="fullscreen"
      @click="emit('fullscreen')"
    />
    <q-btn
      flat
      dense
      square
      no-caps
      icon="keyboard"
      :label="t('live.desktop.toolbar.ctrlAltDel')"
      class="desktop-toolbar__button"
      data-desktop="ctrl-alt-del"
      :disable="!live"
      @click="emit('ctrl-alt-del')"
    />
  </div>
</template>

<style scoped>
.desktop-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0 var(--spacing-xs);
}

.desktop-toolbar__button {
  color: var(--blue-primary);
}
</style>
