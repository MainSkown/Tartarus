<script setup lang="ts">
import { computed } from 'vue'
import type { LanPreset } from '@/api'
import ViewState from '@/components/ViewState.vue'
import { t } from '@/i18n'
import { describeHosts } from '@/services/lan-hosts'

const props = withDefaults(
  defineProps<{
    presets: LanPreset[]
    loading: boolean
    error?: string
    routeRefused?: boolean
    presetError?: string
    disable?: boolean
  }>(),
  { error: undefined, routeRefused: false, presetError: undefined, disable: false },
)
const emit = defineEmits<{ retry: [] }>()
const enabled = defineModel<boolean>('enabled', { required: true })
const preset = defineModel<string | null>('preset', { required: true })

const note = computed(() => {
  if (props.routeRefused) return t('submit.lan.routeRefused')
  return enabled.value ? t('submit.lan.on') : t('submit.lan.off')
})
</script>

<template>
  <div class="lan-fields">
    <q-toggle
      v-model="enabled"
      dense
      :label="t('submit.lan.label')"
      :disable="disable || routeRefused"
      class="lan-toggle text-mono"
    />
    <p class="lan-note text-gray">
      {{ note }}
    </p>

    <ViewState
      v-if="enabled"
      :loading="loading"
      :error="error"
      :empty="presets.length === 0"
      :empty-message="t('submit.lan.preset.none')"
      class="lan-state"
      @retry="emit('retry')"
    >
      <div
        class="preset-list"
        role="radiogroup"
        :aria-label="t('submit.lan.preset.group')"
      >
        <label
          v-for="option in presets"
          :key="option.id"
          class="preset-row"
          :class="{ 'preset-row--selected': preset === option.id }"
        >
          <input
            type="radio"
            name="lan-preset"
            class="preset-radio"
            :value="option.id"
            :checked="preset === option.id"
            :disabled="disable"
            @change="preset = option.id"
          >
          <span class="preset-text">
            <span class="preset-name text-mono">{{ option.name }}</span>
            <span class="preset-description text-gray">{{ option.description }}</span>
            <span class="preset-hosts text-mono">{{ describeHosts(option.hosts) }}</span>
          </span>
        </label>
      </div>
      <p
        v-if="presetError"
        class="field-error preset-error"
        role="alert"
      >
        {{ presetError }}
      </p>
    </ViewState>
  </div>
</template>

<style scoped>
.lan-fields {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  min-width: 0;
}

.lan-toggle {
  align-self: flex-start;
  font-size: 0.8rem;
  letter-spacing: 1px;
}

.lan-note {
  margin: 0;
  font-size: 0.75rem;
  overflow-wrap: anywhere;
}

.lan-fields > .lan-state {
  padding: var(--spacing-md) 0;
}

.preset-list {
  max-height: 20rem;
  overflow-y: auto;
  background: var(--black);
  border: 2px solid var(--border-primary);
}

.preset-row {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm);
  cursor: pointer;
  transition: background-color var(--transition-fast);
}

.preset-row:hover,
.preset-row:focus-within {
  background: var(--hover-bg);
}

.preset-row--selected,
.preset-row--selected:hover {
  background: var(--active-bg);
  color: var(--text-white);
}

.preset-radio {
  flex: none;
  margin: 0.2rem 0 0;
  accent-color: var(--blue-primary);
}

.preset-row--selected .preset-radio {
  accent-color: var(--text-white);
}

.preset-text {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  min-width: 0;
}

.preset-name {
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.preset-description {
  font-size: 0.75rem;
  overflow-wrap: anywhere;
}

.preset-row--selected .preset-description {
  color: var(--blue-lighter);
}

.preset-hosts {
  color: var(--blue-primary);
  font-size: 0.7rem;
  overflow-wrap: anywhere;
}

.preset-row--selected .preset-hosts {
  color: var(--text-white);
}

.field-error {
  margin: 0;
  color: var(--status-critical);
  font-size: 0.75rem;
}
</style>
