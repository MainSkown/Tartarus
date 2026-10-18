<script setup lang="ts">
import type { Guest } from '@/api'
import GuestBadges from '@/components/guest/GuestBadges.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import { t } from '@/i18n'

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
      <div class="guest-state-list__head">
        <span
          class="guest-state-list__name text-mono"
          :title="guest.name"
        >{{ guest.name }}</span>
        <StatusBadge :guest-state="guest.state" />
      </div>
      <GuestBadges
        v-if="(guest.badges ?? []).length > 0"
        class="guest-state-list__tags"
        :badges="guest.badges ?? []"
      />
    </li>
  </ul>
  <TerminalEmpty
    v-else
    :message="t('guests.stateList.empty')"
  />
</template>

<style scoped>
.guest-state-list {
  display: flex;
  flex-direction: column;
  align-self: stretch;
  margin: 0;
  padding: 0;
  list-style: none;
}

/* A divider and a name-and-state line of their own keep a guest with many badges from reading as part of its neighbour. */
.guest-state-list__row {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  padding: var(--spacing-sm) 0;
  border-top: 1px solid var(--border-subtle);
}

.guest-state-list__row:first-child {
  border-top: 0;
  padding-top: 0;
}

.guest-state-list__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-sm);
}

.guest-state-list__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
