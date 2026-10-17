<script setup lang="ts">
import type { Guest } from '@/api'
import GuestStateList from '@/components/guest/GuestStateList.vue'

defineProps<{ guests: readonly Guest[]; message?: string | null }>()
</script>

<template>
  <div class="guest-health-menu">
    <h2 class="guest-health-menu__title text-mono">
      GUEST VM
    </h2>
    <p
      v-if="message"
      class="guest-health-menu__message text-mono text-gray"
    >
      {{ message }}
    </p>
    <GuestStateList :guests="guests" />
    <q-btn
      v-close-popup
      outline
      square
      label="[OPEN GUEST VM]"
      class="guest-health-menu__open text-mono"
      to="/guest"
    />
  </div>
</template>

<style scoped>
.guest-health-menu {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--spacing-sm);
  width: min(22rem, 90vw);
  padding: var(--spacing-md);
}

.guest-health-menu__title {
  margin: 0;
  color: var(--blue-primary);
  font-size: 0.75rem;
  letter-spacing: 2px;
}

.guest-health-menu__message {
  margin: 0;
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.guest-health-menu__open {
  color: var(--blue-primary);
}
</style>
