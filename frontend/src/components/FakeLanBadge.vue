<script setup lang="ts">
import FieldActions from '@/components/FieldActions.vue'
import { t } from '@/i18n'
</script>

<template>
  <span class="fake-lan">
    <q-badge
      outline
      class="fake-lan-badge text-mono"
      :title="t('network.lan.badgeTitle')"
    >
      {{ t('network.lan.badge') }}
    </q-badge>
    <FieldActions
      field="tartarus.lan.simulated"
      value="true"
      :copyable="false"
    />
  </span>
</template>

<style scoped>
.fake-lan {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-xs);
  margin-block: -4px;
  margin-inline-end: var(--spacing-xs);
  vertical-align: middle;
}

.fake-lan-badge {
  color: var(--blue-light);
  font-size: 0.75rem;
  letter-spacing: 1px;
  white-space: nowrap;
}
</style>
