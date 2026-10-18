<script setup lang="ts">
import { computed } from 'vue'
import type { AnalysisRead } from '@/api'
import { t } from '@/i18n'
import { useIocExport } from '@/composables/use-ioc-export'
import { IOC_FORMATS } from '@/services/ioc-export'
import { openReportDialog } from '@/services/report-dialog'
import { REPORT_FORMATS, reportBlockReason } from '@/services/report-request'

/** The entries of the Export menu: IOC downloads, then the report dialog. Shared by the analysis header and the Dashboard row menu. */
const props = defineProps<{ analysis: AnalysisRead }>()

const { download, downloading } = useIocExport()
const reportBlock = computed(() => reportBlockReason(props.analysis.status))
</script>

<template>
  <q-list
    dense
    class="export-entries"
  >
    <q-item-label
      header
      class="export-entries__heading text-mono"
    >
      {{ t('reports.export.iocs') }}
    </q-item-label>
    <q-item
      v-for="format in IOC_FORMATS"
      :key="format.value"
      v-close-popup="-1"
      clickable
      :disable="downloading !== undefined"
      class="export-entries__item text-mono"
      @click="download(analysis.id, format.value)"
    >
      <q-item-section>{{ format.label }}</q-item-section>
    </q-item>

    <q-separator />

    <q-item-label
      header
      class="export-entries__heading text-mono"
    >
      {{ t('reports.export.report') }}
    </q-item-label>
    <q-item
      v-for="format in REPORT_FORMATS"
      :key="format.value"
      v-close-popup="-1"
      clickable
      :disable="reportBlock !== undefined"
      class="export-entries__item text-mono"
      @click="openReportDialog(analysis, format.value)"
    >
      <q-item-section>{{ format.label }}</q-item-section>
    </q-item>
    <p
      v-if="reportBlock"
      class="export-entries__hint text-mono text-gray"
    >
      {{ reportBlock }}
    </p>
  </q-list>
</template>

<style scoped>
.export-entries {
  min-width: 13rem;
  max-width: 16rem;
}

.export-entries__heading {
  padding: var(--spacing-sm) var(--spacing-md) var(--spacing-xs);
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.export-entries__item {
  font-size: 0.85rem;
}

.export-entries__item:hover:not(.disabled) {
  background: var(--hover-bg);
  color: var(--blue-hover);
}

.export-entries__hint {
  margin: 0;
  padding: var(--spacing-xs) var(--spacing-md) var(--spacing-sm);
  font-size: 0.7rem;
  line-height: 1.4;
}
</style>
