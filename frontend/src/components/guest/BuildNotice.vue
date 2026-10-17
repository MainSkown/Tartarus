<script setup lang="ts">
export type NoticeTone = 'amber' | 'red' | 'green'

defineProps<{
  tone: NoticeTone
  title: string
  icon: string
  /** A refusal of the action in the `actions` slot, shown under the buttons it belongs to. */
  error?: string
}>()
</script>

<template>
  <section
    class="build-notice"
    :class="`build-notice--${tone}`"
    :role="tone === 'red' ? 'alert' : 'note'"
  >
    <header class="build-notice__head">
      <q-icon
        :name="icon"
        size="20px"
        aria-hidden="true"
      />
      <h2 class="build-notice__title text-mono">
        {{ title }}
      </h2>
    </header>
    <div class="build-notice__body">
      <slot />
    </div>
    <div
      v-if="$slots.actions"
      class="build-notice__actions"
    >
      <slot name="actions" />
    </div>
    <p
      v-if="error"
      class="build-notice__error text-mono"
      role="alert"
    >
      <q-icon
        name="dangerous"
        size="16px"
        aria-hidden="true"
      />
      <span>{{ error }}</span>
    </p>
  </section>
</template>

<style scoped>
.build-notice {
  --tone: var(--status-medium);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  min-width: 0;
  padding: var(--spacing-md);
  border: 2px solid var(--tone);
  background: var(--dark-bg);
}

.build-notice--red {
  --tone: var(--status-critical);
}

.build-notice--green {
  --tone: var(--status-success);
}

.build-notice__head {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  color: var(--tone);
}

.build-notice__title {
  margin: 0;
  font-size: 0.85rem;
  line-height: 1.2;
  letter-spacing: 2px;
}

.build-notice__body {
  min-width: 0;
  overflow-wrap: anywhere;
}

.build-notice__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-sm);
}

.build-notice__error {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-xs);
  margin: 0;
  color: var(--status-critical);
  font-size: 0.85rem;
  overflow-wrap: anywhere;
}
</style>
