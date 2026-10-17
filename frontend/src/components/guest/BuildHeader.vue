<script setup lang="ts">
import StatusBadge from '@/components/StatusBadge.vue'
import { buildKindLabel, type BuildPhase } from '@/services/guest-build'

defineProps<{
  guest: string
  kind: string
  phase: BuildPhase
  percent: number
  message: string
  /** The quiet way back, left out where the verdict offers [OPEN GUEST VM]. */
  backLink: boolean
}>()
</script>

<template>
  <header
    class="build-header"
    data-build="header"
  >
    <div class="build-header__title">
      <span
        class="build-header__kind text-mono"
        data-build="kind"
      >{{ buildKindLabel(kind) }}</span>
      <h1 class="build-header__guest text-mono">
        <router-link
          to="/guest"
          :title="guest"
        >
          {{ guest }}
        </router-link>
      </h1>
      <StatusBadge :build-phase="phase" />
      <q-btn
        v-if="backLink"
        flat
        dense
        square
        no-caps
        label="[BACK TO GUEST VM]"
        class="build-header__back text-mono"
        to="/guest"
      />
    </div>
    <progress
      :value="percent"
      max="100"
      :aria-label="`${guest} ${buildKindLabel(kind).toLowerCase()} progress`"
    />
    <p class="build-header__message text-mono text-gray">
      <span data-build="percent">{{ percent }}%</span>
      <span data-build="message">{{ message }}</span>
    </p>
  </header>
</template>

<style scoped>
.build-header {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  min-width: 0;
}

.build-header__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-sm);
  min-width: 0;
}

.build-header__kind {
  padding: 1px 6px;
  border: 1px solid var(--blue-primary);
  color: var(--blue-primary);
  font-size: 0.75rem;
  letter-spacing: 1px;
}

.build-header__guest {
  flex: 0 1 auto;
  min-width: 0;
  margin: 0;
  overflow: hidden;
  font-size: 1.25rem;
  font-weight: 600;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.build-header__guest a {
  color: var(--text-white);
  text-decoration: none;
}

.build-header__guest a:hover {
  color: var(--blue-light);
}

.build-header__back {
  margin-left: auto;
  color: var(--text-gray);
  font-size: 0.75rem;
}

.build-header__message {
  display: flex;
  gap: var(--spacing-sm);
  margin: 0;
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.build-header__message [data-build='percent'] {
  flex: none;
}
</style>
