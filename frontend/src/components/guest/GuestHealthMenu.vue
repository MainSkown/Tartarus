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
    <div class="guest-health-menu__list">
      <GuestStateList :guests="guests" />
    </div>
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

/* Only the list scrolls: the title, the message and the link to the page stay where they are. */
.guest-health-menu__list {
  align-self: stretch;
  min-height: 0;
  max-height: clamp(10rem, calc(100vh - 27rem), 24rem);
  overflow-y: auto;
}

.guest-health-menu__open {
  color: var(--blue-primary);
}
</style>
