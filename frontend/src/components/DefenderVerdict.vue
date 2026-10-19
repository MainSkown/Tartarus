<script setup lang="ts">
import { computed } from 'vue'
import type { DefenderVerdict } from '@/api'
import DefenderThreatRow from '@/components/DefenderThreatRow.vue'
import { t } from '@/i18n'
import { verdictHeadline } from '@/services/defender-verdict'

const props = defineProps<{ verdict: DefenderVerdict }>()

const headline = computed(() => verdictHeadline(props.verdict))
const prominent = computed(() => props.verdict.blocked_before_run)
</script>

<template>
  <div
    class="defender-verdict"
    :class="[`defender-verdict--${verdict.status}`, { 'defender-verdict--prominent': prominent }]"
    :style="{ borderLeftColor: `var(${headline.color})` }"
  >
    <p class="defender-verdict__headline text-mono">
      <q-icon
        :name="headline.icon"
        :style="{ color: `var(${headline.color})` }"
        size="20px"
        aria-hidden="true"
      />
      <span>{{ t(headline.messageKey) }}</span>
    </p>
    <p
      v-if="headline.detailKey"
      class="defender-verdict__detail text-gray"
    >
      {{ t(headline.detailKey) }}
    </p>
    <ul
      v-if="verdict.threats.length > 0"
      class="defender-verdict__threats"
    >
      <DefenderThreatRow
        v-for="threat in verdict.threats"
        :key="threat.detection_id"
        :threat="threat"
      />
    </ul>
  </div>
</template>

<style scoped>
.defender-verdict {
  min-width: 0;
  padding: var(--spacing-sm) var(--spacing-md);
  border: 1px solid var(--border-primary);
  border-left-width: 3px;
  background: var(--card-bg);
}

.defender-verdict--no_export .defender-verdict__headline,
.defender-verdict--clean .defender-verdict__headline {
  color: var(--text-gray);
}

.defender-verdict--prominent {
  margin-bottom: var(--spacing-lg);
  padding: var(--spacing-md) var(--spacing-lg);
  border: 2px solid var(--blue-primary);
  border-left-width: 6px;
  box-shadow: var(--shadow-blue-weak);
}

.defender-verdict__headline {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin: 0;
  font-weight: bold;
  overflow-wrap: anywhere;
}

.defender-verdict--prominent .defender-verdict__headline {
  font-size: 1.15rem;
}

.defender-verdict__detail {
  margin: var(--spacing-xs) 0 0;
}

.defender-verdict__threats {
  margin: var(--spacing-sm) 0 0;
  padding: 0;
  list-style: none;
}
</style>
