<script setup lang="ts">
import type { CheckState } from '@/composables/use-guest-list'
import { checkSummary } from '@/services/guest-view'

defineProps<{ state: CheckState }>()
</script>

<template>
  <section
    class="guest-checks"
    aria-label="Health checks"
  >
    <template v-if="state.busy">
      <progress aria-label="Running the checks" />
      <p
        class="guest-checks__note text-mono text-gray"
        role="status"
      >
        running the checks, this takes up to 2 minutes
      </p>
    </template>

    <p
      v-else-if="state.error"
      class="guest-checks__error text-mono"
      role="alert"
    >
      <q-icon
        name="dangerous"
        size="16px"
        aria-hidden="true"
      />
      <span>{{ state.error }}</span>
    </p>

    <template v-else-if="state.result">
      <p class="guest-checks__note text-mono text-gray">
        {{ checkSummary(state.result.checks) }}
      </p>
      <ul class="guest-checks__list">
        <li
          v-for="probe in state.result.checks"
          :key="probe.id"
          class="guest-checks__row"
          :class="{ 'guest-checks__row--failed': !probe.ok }"
        >
          <q-icon
            :name="probe.ok ? 'check_circle' : 'dangerous'"
            size="16px"
            aria-hidden="true"
          />
          <span class="guest-checks__id text-mono">{{ probe.id }}</span>
          <span class="sr-only">{{ probe.ok ? 'passed' : 'failed' }}</span>
          <span class="guest-checks__message">{{ probe.message }}</span>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.guest-checks {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm);
  border: 1px solid var(--border-subtle);
  background: var(--black);
}

.guest-checks__note,
.guest-checks__error {
  margin: 0;
  font-size: 0.8rem;
}

.guest-checks__error {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-xs);
  color: var(--status-critical);
  overflow-wrap: anywhere;
}

.guest-checks__list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  margin: 0;
  padding: 0;
  list-style: none;
}

.guest-checks__row {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr);
  gap: var(--spacing-sm);
  align-items: baseline;
  color: var(--status-success);
  font-size: 0.85rem;
}

.guest-checks__row--failed {
  color: var(--status-critical);
}

.guest-checks__row .q-icon {
  align-self: center;
}

.guest-checks__message {
  min-width: 0;
  color: var(--text-gray-light);
  overflow-wrap: anywhere;
}
</style>
