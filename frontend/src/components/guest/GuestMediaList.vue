<script setup lang="ts">
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import { I18nT, t } from '@/i18n'
import type { MediaChoice } from '@/composables/use-guest-wizard'
import { formatFileSize } from '@/services/file-size'
import { ISO_FOLDER, mediaDetails } from '@/services/guest-media-view'

defineProps<{ choices: MediaChoice[]; selected?: string; error?: string }>()
const emit = defineEmits<{ select: [file: string]; reload: [] }>()
</script>

<template>
  <div
    class="media-list"
    :class="{ 'media-list--empty': choices.length === 0 }"
  >
    <div
      v-if="choices.length > 0"
      class="media-list__rows"
      role="radiogroup"
      :aria-label="t('guests.media.label')"
    >
      <button
        v-for="{ entry, profileName, unavailable } in choices"
        :key="entry.file"
        type="button"
        role="radio"
        class="media-row"
        :class="{ 'media-row--selected': entry.file === selected, 'media-row--unavailable': unavailable }"
        :aria-checked="entry.file === selected"
        :aria-disabled="Boolean(unavailable)"
        @click="!unavailable && emit('select', entry.file)"
      >
        <span
          class="media-row__mark"
          aria-hidden="true"
        />
        <span class="media-row__body">
          <span class="media-row__head">
            <span
              class="media-row__file text-mono"
              :title="entry.file"
            >{{ entry.file }}</span>
            <span class="media-row__size text-mono">{{ formatFileSize(entry.size) }}</span>
          </span>
          <span
            v-if="unavailable"
            class="media-row__error text-mono"
          >{{ unavailable }}</span>
          <span
            v-else
            class="media-row__details"
          >
            <span
              v-if="profileName"
              class="media-row__profile text-mono"
            >{{ profileName }}</span>
            <span
              v-for="detail in mediaDetails(entry)"
              :key="detail"
              class="media-row__detail text-mono"
            >{{ detail }}</span>
          </span>
        </span>
      </button>
    </div>

    <div
      v-else
      class="media-list__empty"
    >
      <TerminalEmpty :message="t('guests.media.empty')" />
      <I18nT
        keypath="guests.media.hint"
        scope="global"
        tag="p"
        class="media-list__hint"
      >
        <template #folder>
          <code>{{ ISO_FOLDER }}</code>
        </template>
      </I18nT>
    </div>

    <p
      v-if="error"
      class="media-list__error text-mono"
      role="alert"
    >
      {{ error }}
    </p>

    <q-btn
      flat
      square
      :label="t('guests.action.reload')"
      class="media-list__reload text-mono"
      @click="emit('reload')"
    />
  </div>
</template>

<style scoped>
.media-list {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--spacing-sm);
  min-width: 0;
}

.media-list--empty {
  align-items: center;
}

.media-list--empty .media-list__reload {
  padding-left: 16px;
}

.media-list__rows {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  width: 100%;
}

.media-row {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-md);
  width: 100%;
  min-width: 0;
  padding: var(--spacing-sm) var(--spacing-md);
  border: 2px solid var(--border-primary);
  background: var(--black);
  color: var(--text-white);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    border-color var(--transition-fast),
    background-color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.media-row:hover:not([aria-disabled='true']),
.media-row:focus-visible {
  border-color: var(--blue-primary);
  background: var(--hover-bg);
  box-shadow: var(--shadow-blue-weak);
}

.media-row--selected {
  border-color: var(--blue-primary);
  background: var(--hover-bg);
}

.media-row[aria-disabled='true'] {
  border-color: var(--border-subtle);
  background: var(--dark-bg);
  cursor: not-allowed;
}

.media-row__mark {
  flex: none;
  width: 14px;
  height: 14px;
  margin-top: 3px;
  border: 2px solid var(--border-secondary);
}

.media-row--selected .media-row__mark {
  border-color: var(--blue-primary);
  background: var(--blue-primary);
  box-shadow: inset 0 0 0 2px var(--black);
}

.media-row__body {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  gap: var(--spacing-xs);
  min-width: 0;
}

.media-row__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--spacing-md);
}

.media-row__file {
  min-width: 0;
  overflow-wrap: anywhere;
}

.media-row--unavailable .media-row__file {
  color: var(--text-gray);
}

.media-row__size {
  flex: none;
  color: var(--text-gray);
  font-size: 0.8rem;
}

.media-row__details {
  display: flex;
  flex-wrap: wrap;
  gap: 0 var(--spacing-md);
  color: var(--text-gray);
  font-size: 0.8rem;
}

.media-row__profile {
  color: var(--blue-light);
}

.media-row__error {
  color: var(--status-critical);
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.media-list__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  padding: var(--spacing-md) 0;
}

.media-list__hint {
  margin: 0;
  max-width: 60ch;
  color: var(--text-gray);
  text-align: center;
}

.media-list__error {
  margin: 0;
  color: var(--status-critical);
  font-size: 0.8rem;
}

.media-list__reload {
  padding-left: 0;
  color: var(--blue-primary);
}
</style>
