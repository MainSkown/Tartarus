<script setup lang="ts">
defineProps<{ label: string }>()
</script>

<template>
  <div class="guest-field">
    <dt class="guest-field__label text-mono">
      {{ label }}
    </dt>
    <dd class="guest-field__value">
      <slot />
    </dd>
  </div>
</template>

<style scoped>
.guest-field {
  display: grid;
  grid-template-columns: 7rem minmax(0, 1fr);
  gap: var(--spacing-sm);
  align-items: baseline;
}

.guest-field__label {
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.guest-field__value {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
}
</style>
