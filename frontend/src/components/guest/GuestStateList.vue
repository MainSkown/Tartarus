<script setup lang="ts">
import type { Guest } from '@/api'
import GuestBadges from '@/components/guest/GuestBadges.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import TerminalEmpty from '@/components/TerminalEmpty.vue'

defineProps<{ guests: readonly Guest[] }>()
</script>

<template>
  <ul
    v-if="guests.length > 0"
    class="guest-state-list"
  >
    <li
      v-for="guest in guests"
      :key="guest.name"
      class="guest-state-list__row"
    >
      <span
        class="guest-state-list__name text-mono"
        :title="guest.name"
      >{{ guest.name }}</span>
      <StatusBadge :guest-state="guest.state" />
      <GuestBadges :badges="guest.badges ?? []" />
    </li>
  </ul>
  <TerminalEmpty
    v-else
    message="no guests"
  />
</template>

<style scoped>
.guest-state-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  margin: 0;
  padding: 0;
  list-style: none;
}

.guest-state-list__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-xs) var(--spacing-sm);
}

.guest-state-list__name {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
