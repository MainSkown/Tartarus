<script setup lang="ts">
import type { AttackMatrix, AttackTechniqueHit } from '@/api'
import { t } from '@/i18n'
import { severityMeta } from '@/services/analysis-status'

defineProps<{ matrix: AttackMatrix }>()
const emit = defineEmits<{ select: [technique: AttackTechniqueHit] }>()

function cellLabel(technique: AttackTechniqueHit): string {
  const values = { id: technique.id, hits: technique.hit_count, severity: technique.severity }
  return technique.name
    ? t('detections.matrix.cellNamed', { ...values, name: technique.name }, technique.hit_count)
    : t('detections.matrix.cell', values, technique.hit_count)
}
</script>

<template>
  <div class="attack-matrix">
    <p class="attack-matrix__version text-mono text-gray">
      {{ t('detections.matrix.version', { version: matrix.attack_version }) }}
    </p>
    <div class="attack-matrix__scroll">
      <section
        v-for="tactic in matrix.tactics"
        :key="tactic.id"
        class="attack-tactic"
      >
        <h3 class="attack-tactic__name text-mono">
          {{ tactic.name }}
        </h3>
        <button
          v-for="technique in tactic.techniques"
          :key="technique.id"
          type="button"
          class="attack-cell"
          :style="{ '--severity': `var(${severityMeta(technique.severity).color})` }"
          :aria-label="cellLabel(technique)"
          @click="emit('select', technique)"
        >
          <q-icon
            :name="severityMeta(technique.severity).icon"
            size="16px"
            class="attack-cell__icon"
            aria-hidden="true"
          />
          <span class="attack-cell__id text-mono">{{ technique.id }}</span>
          <span class="attack-cell__count text-mono">{{ technique.hit_count }}</span>
          <span
            v-if="technique.name"
            class="attack-cell__name"
          >{{ technique.name }}</span>
        </button>
      </section>
    </div>
  </div>
</template>

<style scoped>
.attack-matrix__version {
  margin: 0 0 var(--spacing-sm);
  font-size: 0.8rem;
}

.attack-matrix__scroll {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-sm);
  padding-bottom: var(--spacing-sm);
  overflow-x: auto;
}

.attack-tactic {
  display: flex;
  flex: 0 0 12rem;
  flex-direction: column;
  gap: var(--spacing-sm);
  min-width: 0;
}

.attack-tactic__name {
  margin: 0;
  padding: var(--spacing-sm);
  border-bottom: 2px solid var(--border-primary);
  color: var(--blue-primary);
  font-size: 0.75rem;
  line-height: 1.2;
  letter-spacing: 1px;
  text-transform: uppercase;
}

.attack-cell {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: baseline;
  gap: 2px var(--spacing-sm);
  padding: var(--spacing-sm);
  border: 1px solid var(--severity);
  border-left-width: 4px;
  background: var(--dark-bg);
  color: var(--text-white);
  text-align: left;
  cursor: pointer;
  transition: background-color var(--transition-fast), box-shadow var(--transition-fast);
}

.attack-cell:hover,
.attack-cell:focus-visible {
  background: var(--hover-bg);
  box-shadow: var(--shadow-blue-medium);
}

.attack-cell__icon {
  align-self: center;
  color: var(--severity);
}

.attack-cell__id {
  font-weight: bold;
}

.attack-cell__count {
  color: var(--severity);
  font-weight: bold;
}

.attack-cell__name {
  grid-column: 1 / -1;
  font-size: 0.85rem;
  overflow-wrap: anywhere;
}
</style>
