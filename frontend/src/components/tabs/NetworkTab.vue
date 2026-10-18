<script setup lang="ts">
import { computed, ref } from 'vue'
import { viewsNetwork } from '@/api'
import type { AnalysisRead, NetworkView } from '@/api'
import NetworkTable, { type NetworkColumn, type NetworkTableRow } from '@/components/NetworkTable.vue'
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import ViewState from '@/components/ViewState.vue'
import { useAnalysisView } from '@/composables/use-analysis-view'
import { t } from '@/i18n'
import { filterOn, flowDestinationFilters, hostEntryFilters, type EventsFilter } from '@/services/events-filters'
import { formatTimestamp } from '@/services/format-time'

const props = defineProps<{ analysis: AnalysisRead }>()

type ListName = 'dns' | 'http' | 'tls' | 'flows' | 'alerts' | 'hosts'
type Item<List extends ListName> = NetworkView[List]['items'][number]
type Cell = string | number | null

interface ValueColumn<Row> extends NetworkColumn {
  value: (row: Row) => Cell
  /** What the cell's "show events" button applies; no filters, no button. */
  filters?: (row: Row) => EventsFilter[]
}

interface SubTab {
  key: ListName
  label: string
  emptyMessage: string
  emptyNote?: string
  withProcess: boolean
  columns: NetworkColumn[]
  rows: (view: NetworkView) => NetworkTableRow[]
}

interface SubTabSpec<List extends ListName> {
  label: string
  emptyMessage: string
  emptyNote?: string
  columns: ValueColumn<Item<List>>[]
  rowKey: (row: Item<List>) => string
}

function subTab<List extends ListName>(key: List, spec: SubTabSpec<List>): SubTab {
  const { columns, rowKey, ...labels } = spec
  return {
    key,
    ...labels,
    withProcess: key !== 'hosts',
    columns: columns.map(({ label, numeric }) => ({ label, numeric })),
    rows: (view) =>
      (view[key].items as Item<List>[]).map((row) => ({
        key: rowKey(row),
        cells: columns.map((column) => column.value(row)),
        cellFilters: columns.map((column) => column.filters?.(row) ?? []),
        process: 'process' in row ? row.process : null,
      })),
  }
}

const timeColumn = <Row extends { time: string }>(): ValueColumn<Row> => ({
  label: t('network.column.time'),
  value: (row) => formatTimestamp(row.time),
})

const endpoint = (ip: string | null, port: number | null): string | null =>
  ip === null ? null : port === null ? ip : `${ip}:${port}`

const eventId = (row: { event_id: string }): string => row.event_id

function buildSubTabs(): SubTab[] {
  return [
    subTab('dns', {
      label: t('network.subTab.dns'),
      emptyMessage: t('network.empty.dns'),
      columns: [
        timeColumn(),
        { label: t('network.column.query'), value: (row) => row.query, filters: (row) => filterOn('dns.question.name', row.query) },
        { label: t('network.column.type'), value: (row) => row.type },
        { label: t('network.column.answers'), value: (row) => row.answers.join(', ') || null },
      ],
      rowKey: eventId,
    }),
    subTab('http', {
      label: t('network.subTab.http'),
      emptyMessage: t('network.empty.http'),
      columns: [
        timeColumn(),
        { label: t('network.column.method'), value: (row) => row.method },
        { label: t('network.column.url'), value: (row) => row.url, filters: (row) => filterOn('url.full', row.url) },
        { label: t('network.column.status'), value: (row) => row.status },
        { label: t('network.column.userAgent'), value: (row) => row.user_agent },
        { label: t('network.column.host'), value: (row) => row.host },
      ],
      rowKey: eventId,
    }),
    subTab('tls', {
      label: t('network.subTab.tls'),
      emptyMessage: t('network.empty.tls'),
      emptyNote: t('network.notYetSourced'),
      columns: [
        timeColumn(),
        { label: t('network.column.sni'), value: (row) => row.server_name, filters: (row) => filterOn('tls.server.sni', row.server_name) },
        { label: t('network.column.ja3'), value: (row) => row.ja3 },
        { label: t('network.column.ja3s'), value: (row) => row.ja3s },
      ],
      rowKey: eventId,
    }),
    subTab('flows', {
      label: t('network.subTab.flows'),
      emptyMessage: t('network.empty.flows'),
      columns: [
        timeColumn(),
        { label: t('network.column.transport'), value: (row) => row.transport },
        { label: t('network.column.source'), value: (row) => endpoint(row.source_ip, row.source_port) },
        {
          label: t('network.column.destination'),
          value: (row) => endpoint(row.destination_ip, row.destination_port),
          filters: (row) => flowDestinationFilters(row.destination_ip, row.destination_port),
        },
      ],
      rowKey: eventId,
    }),
    subTab('alerts', {
      label: t('network.subTab.alerts'),
      emptyMessage: t('network.empty.alerts'),
      emptyNote: t('network.notYetSourced'),
      columns: [
        timeColumn(),
        { label: t('network.column.signature'), value: (row) => row.signature },
        { label: t('network.column.severity'), value: (row) => row.severity },
      ],
      rowKey: eventId,
    }),
    subTab('hosts', {
      label: t('network.subTab.hosts'),
      emptyMessage: t('network.empty.hosts'),
      columns: [
        { label: t('network.column.host'), value: (row) => row.host, filters: (row) => hostEntryFilters(row.kind, row.host) },
        { label: t('network.column.kind'), value: (row) => row.kind },
        { label: t('network.column.count'), value: (row) => row.count, numeric: true },
        { label: t('network.column.related'), value: (row) => row.related.join(', ') || null },
      ],
      rowKey: (row) => row.host,
    }),
  ]
}

const subTabs = computed(() => buildSubTabs())

const selectedKey = ref<ListName>('dns')
const selected = computed(() => subTabs.value.find((tab) => tab.key === selectedKey.value)!)
const pcapUrl = computed(() => `/api/analyses/${props.analysis.id}/pcap`)

const { data, loading, error, reload } = useAnalysisView<NetworkView>(
  () => props.analysis.id,
  (analysisId) => viewsNetwork({ path: { analysis_id: analysisId } }),
)

const total = computed(() => data.value?.[selectedKey.value].total ?? 0)
const rows = computed(() => (data.value ? selected.value.rows(data.value) : []))
</script>

<template>
  <section data-tab="network">
    <ViewState
      :loading="loading"
      :error="error"
      @retry="reload"
    >
      <template v-if="data">
        <div class="network-bar">
          <nav
            class="network-subtabs"
            role="tablist"
            :aria-label="t('network.tabsLabel')"
          >
            <button
              v-for="tab in subTabs"
              :key="tab.key"
              type="button"
              role="tab"
              class="network-subtabs__tab text-mono"
              :aria-selected="tab.key === selectedKey"
              @click="selectedKey = tab.key"
            >
              {{ t('network.subTab.withCount', { label: tab.label, count: data[tab.key].total }) }}
            </button>
          </nav>
          <q-btn
            outline
            square
            no-caps
            dense
            class="network-bar__pcap text-mono"
            :label="t('network.pcap')"
            :href="pcapUrl"
            download
          />
        </div>

        <div
          v-if="total === 0"
          class="network-empty"
        >
          <TerminalEmpty :message="selected.emptyMessage" />
          <p
            v-if="selected.emptyNote"
            class="network-note text-mono text-gray"
          >
            {{ selected.emptyNote }}
          </p>
        </div>
        <NetworkTable
          v-else
          :columns="selected.columns"
          :rows="rows"
          :total="total"
          :with-process="selected.withProcess"
          :simulated="data.simulated"
        />
      </template>
    </ViewState>
  </section>
</template>

<style scoped>
section {
  min-width: 0;
  padding: var(--spacing-lg);
}

.network-bar {
  display: flex;
  align-items: flex-end;
  gap: var(--spacing-md);
}

.network-subtabs {
  display: flex;
  flex: 1 1 0;
  flex-wrap: wrap;
  min-width: 0;
  border-bottom: 2px solid var(--border-primary);
}

.network-subtabs__tab {
  padding: var(--spacing-sm) var(--spacing-md);
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  background: transparent;
  color: var(--text-gray);
  font-size: 0.75rem;
  letter-spacing: 1px;
  cursor: pointer;
  transition: color var(--transition-fast), background-color var(--transition-fast);
}

.network-subtabs__tab:hover {
  background: var(--hover-bg);
  color: var(--blue-hover);
}

.network-subtabs__tab[aria-selected='true'] {
  border-bottom-color: var(--blue-primary);
  color: var(--blue-primary);
}

.network-bar__pcap {
  color: var(--blue-primary);
  flex: none;
  font-size: 0.75rem;
}

.network-empty :deep(.terminal-empty) {
  margin-bottom: 0;
}

.network-note {
  margin: 0;
  padding: 0 var(--spacing-md);
  font-size: 0.75rem;
}
</style>
