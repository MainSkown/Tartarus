<script setup lang="ts">
import CopyButton from '@/components/CopyButton.vue'
import { t } from '@/i18n'

defineProps<{
  label: string
  hash: string | null
  /** Why there is no hash yet; the title of the not-recorded text. */
  absentHint?: string
}>()
</script>

<template>
  <div
    class="hash-row"
    :class="{ 'hash-row--absent': hash === null }"
  >
    <span class="hash-row__label text-mono">{{ label }}</span>
    <template v-if="hash !== null">
      <code
        class="hash-row__hash text-mono"
        :title="hash"
      >{{ hash }}</code>
      <CopyButton
        :text="hash"
        :what="label"
      />
    </template>
    <span
      v-else
      class="hash-row__absent text-mono"
      :title="absentHint"
    >{{ t('analysis.header.notRecorded') }}</span>
  </div>
</template>

<style scoped>
.hash-row {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-sm);
  flex-wrap: var(--hash-row-wrap, nowrap);
  min-height: var(--hash-row-height, 0);
}

.hash-row--absent {
  padding-top: var(--hash-row-text-offset, 0);
}

.hash-row__label {
  flex: none;
  flex-basis: var(--hash-row-label-basis, auto);
  min-width: var(--hash-row-label-width, 0);
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.hash-row__hash {
  flex: var(--hash-row-hash-flex, 0 1 auto);
  min-width: 0;
  color: var(--text-gray);
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.hash-row__absent {
  color: var(--text-gray-dark);
  font-size: 0.65rem;
  letter-spacing: 1px;
  cursor: help;
}
</style>
