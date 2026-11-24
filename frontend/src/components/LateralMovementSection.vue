<script setup lang="ts">
import type { LanSummary } from '@/api'
import LanHostCard from '@/components/LanHostCard.vue'
import LiveNotice from '@/components/LiveNotice.vue'
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import { t } from '@/i18n'

/** The body of the Summary's Lateral movement section; `lan` is absent when the analysis did not ask for a fake network. */
defineProps<{ lan: LanSummary | null | undefined }>()
</script>

<template>
  <div
    v-if="lan"
    class="lan-summary"
  >
    <p class="lan-summary__preset text-mono text-gray">
      {{ t('analysis.summary.lan.preset', { name: lan.preset.name }) }}
    </p>
    <LiveNotice
      v-if="lan.truncated"
      level="warning"
    >
      {{ t('analysis.summary.lan.truncated') }}
    </LiveNotice>
    <TerminalEmpty
      v-if="lan.hosts.length === 0"
      :message="t('analysis.summary.lan.empty')"
    />
    <div
      v-else
      class="lan-summary__hosts"
    >
      <LanHostCard
        v-for="host in lan.hosts"
        :key="host.fqdn"
        :host="host"
      />
    </div>
  </div>
</template>

<style scoped>
.lan-summary {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  min-width: 0;
}

.lan-summary__preset {
  margin: 0;
  font-size: 0.75rem;
  overflow-wrap: anywhere;
}

.lan-summary__hosts {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.lan-summary :deep(.terminal-empty) {
  padding: 0;
}
</style>
