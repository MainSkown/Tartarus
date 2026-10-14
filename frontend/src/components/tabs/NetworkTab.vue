<script setup lang="ts">
import { computed, ref } from 'vue'
import { viewsNetwork } from '@/api'
import type { AnalysisRead, NetworkView } from '@/api'
import NetworkTable, { type NetworkColumn, type NetworkTableRow } from '@/components/NetworkTable.vue'
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import ViewState from '@/components/ViewState.vue'
import { useAnalysisView } from '@/composables/use-analysis-view'
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

const NOT_YET_SOURCED = 'TLS and Suricata alerts arrive with a later milestone'

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
  label: 'TIME',
  value: (row) => formatTimestamp(row.time),
})

const endpoint = (ip: string | null, port: number | null): string | null =>
  ip === null ? null : port === null ? ip : `${ip}:${port}`

const eventId = (row: { event_id: string }): string => row.event_id

const SUB_TABS: SubTab[] = [
  subTab('dns', {
    label: 'DNS',
    emptyMessage: 'no DNS queries recorded',
    columns: [
      timeColumn(),
      { label: 'QUERY', value: (row) => row.query, filters: (row) => filterOn('dns.question.name', row.query) },
      { label: 'TYPE', value: (row) => row.type },
      { label: 'ANSWERS', value: (row) => row.answers.join(', ') || null },
    ],
    rowKey: eventId,
  }),
  subTab('http', {
    label: 'HTTP',
    emptyMessage: 'no HTTP requests recorded',
    columns: [
      timeColumn(),
      { label: 'METHOD', value: (row) => row.method },
      { label: 'URL', value: (row) => row.url, filters: (row) => filterOn('url.full', row.url) },
      { label: 'STATUS', value: (row) => row.status },
      { label: 'USER AGENT', value: (row) => row.user_agent },
      { label: 'HOST', value: (row) => row.host },
    ],
    rowKey: eventId,
  }),
  subTab('tls', {
    label: 'TLS',
    emptyMessage: 'no TLS handshakes recorded',
    emptyNote: NOT_YET_SOURCED,
    columns: [
      timeColumn(),
      { label: 'SNI', value: (row) => row.server_name, filters: (row) => filterOn('tls.server.sni', row.server_name) },
      { label: 'JA3', value: (row) => row.ja3 },
      { label: 'JA3S', value: (row) => row.ja3s },
    ],
    rowKey: eventId,
  }),
  subTab('flows', {
    label: 'FLOWS',
    emptyMessage: 'no flows recorded',
    columns: [
      timeColumn(),
      { label: 'TRANSPORT', value: (row) => row.transport },
      { label: 'SOURCE', value: (row) => endpoint(row.source_ip, row.source_port) },
      {
        label: 'DESTINATION',
        value: (row) => endpoint(row.destination_ip, row.destination_port),
        filters: (row) => flowDestinationFilters(row.destination_ip, row.destination_port),
      },
    ],
    rowKey: eventId,
  }),
  subTab('alerts', {
    label: 'ALERTS',
    emptyMessage: 'no alerts recorded',
    emptyNote: NOT_YET_SOURCED,
    columns: [
      timeColumn(),
      { label: 'SIGNATURE', value: (row) => row.signature },
      { label: 'SEVERITY', value: (row) => row.severity },
    ],
    rowKey: eventId,
  }),
  subTab('hosts', {
    label: 'HOSTS',
    emptyMessage: 'no hosts recorded',
    columns: [
      { label: 'HOST', value: (row) => row.host, filters: (row) => hostEntryFilters(row.kind, row.host) },
      { label: 'KIND', value: (row) => row.kind },
      { label: 'COUNT', value: (row) => row.count, numeric: true },
      { label: 'RELATED', value: (row) => row.related.join(', ') || null },
    ],
    rowKey: (row) => row.host,
  }),
]

const selectedKey = ref<ListName>('dns')
const selected = computed(() => SUB_TABS.find((tab) => tab.key === selectedKey.value)!)
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
            aria-label="Network lists"
          >
            <button
              v-for="tab in SUB_TABS"
              :key="tab.key"
              type="button"
              role="tab"
              class="network-subtabs__tab text-mono"
              :aria-selected="tab.key === selectedKey"
              @click="selectedKey = tab.key"
            >
              {{ tab.label }} ({{ data[tab.key].total }})
            </button>
          </nav>
          <q-btn
            outline
            square
            no-caps
            dense
            class="network-bar__pcap text-mono"
            label="⇩ PCAP"
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
