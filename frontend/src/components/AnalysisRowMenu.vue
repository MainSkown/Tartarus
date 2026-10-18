<script setup lang="ts">
import { computed } from 'vue'
import type { AnalysisRead } from '@/api'
import ExportEntries from '@/components/ExportEntries.vue'
import { t } from '@/i18n'
import { canReingest, isTerminalStatus } from '@/services/analysis-status'

const props = defineProps<{ analysis: AnalysisRead }>()

const emit = defineEmits<{
  open: [id: number]
  reingest: [id: number]
  cancel: [id: number]
  remove: [id: number]
}>()

const reingestable = computed(() => canReingest(props.analysis.status))
const finished = computed(() => isTerminalStatus(props.analysis.status))
</script>

<template>
  <q-btn
    flat
    dense
    square
    icon="more_vert"
    size="sm"
    class="row-menu__button"
    aria-haspopup="menu"
    :aria-label="t('dashboard.row.actionsFor', { id: analysis.id })"
    @click.stop
    @keydown.enter.stop
  >
    <q-tooltip>{{ t('dashboard.row.actions') }}</q-tooltip>
    <q-menu
      anchor="bottom right"
      self="top right"
    >
      <q-list
        dense
        class="row-menu text-mono"
      >
        <q-item
          v-close-popup
          clickable
          @click="emit('open', analysis.id)"
        >
          <q-item-section>{{ t('dashboard.row.open') }}</q-item-section>
        </q-item>
        <q-item
          v-if="reingestable"
          v-close-popup
          clickable
          @click="emit('reingest', analysis.id)"
        >
          <q-item-section>{{ t('dashboard.row.reingest') }}</q-item-section>
        </q-item>
        <q-item clickable>
          <q-item-section>{{ t('dashboard.row.export') }}</q-item-section>
          <q-item-section side>
            <q-icon name="keyboard_arrow_right" />
          </q-item-section>
          <q-menu
            anchor="top start"
            self="top end"
          >
            <ExportEntries :analysis="analysis" />
          </q-menu>
        </q-item>
        <q-item
          v-if="finished"
          v-close-popup
          clickable
          class="row-menu__danger"
          @click="emit('remove', analysis.id)"
        >
          <q-item-section>{{ t('dashboard.row.delete') }}</q-item-section>
        </q-item>
        <q-item
          v-else
          v-close-popup
          clickable
          @click="emit('cancel', analysis.id)"
        >
          <q-item-section>{{ t('dashboard.row.cancel') }}</q-item-section>
        </q-item>
      </q-list>
    </q-menu>
  </q-btn>
</template>

<style scoped>
.row-menu {
  min-width: 9rem;
  font-size: 0.85rem;
}

.row-menu :deep(.q-item:hover) {
  background: var(--hover-bg);
  color: var(--blue-hover);
}

.row-menu .row-menu__danger {
  color: var(--status-critical);
}
</style>
