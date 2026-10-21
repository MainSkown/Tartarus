<script setup lang="ts">
import GuestChip from '@/components/GuestChip.vue'
import type { GuestOption } from '@/composables/use-guest-choice'
import { t } from '@/i18n'

defineProps<{ option: GuestOption }>()
</script>

<template>
  <span class="guest-option-row text-mono">
    <GuestChip
      :name="option.name"
      :badges="option.badges"
    />
    <span
      v-if="option.profileName"
      class="guest-option-row__profile"
    >{{ option.profileName }}</span>
    <span
      v-if="option.busy"
      class="guest-option-row__busy"
    >{{ t('submit.guest.busy') }}</span>
    <span
      v-if="option.reason"
      class="guest-option-row__reason"
    >{{ option.reason }}</span>
  </span>
</template>

<style scoped>
.guest-option-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--spacing-xs) var(--spacing-sm);
  min-width: 0;
}

.guest-option-row__profile {
  color: var(--text-gray);
  font-size: 0.75rem;
  white-space: nowrap;
}

.guest-option-row__busy {
  margin-left: auto;
  color: var(--status-medium);
  font-size: 0.7rem;
  letter-spacing: 1px;
  text-transform: uppercase;
  white-space: nowrap;
}

.guest-option-row__reason {
  margin-left: auto;
  color: var(--status-medium);
  font-size: 0.7rem;
  letter-spacing: 1px;
  text-transform: uppercase;
}
</style>
