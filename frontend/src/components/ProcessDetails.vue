<script setup lang="ts">
import { computed, ref } from 'vue'
import { viewsProcess, type ProcessNode, type ProcessRef } from '@/api'
import FilterEventsButton from '@/components/FilterEventsButton.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import SeverityBadge from '@/components/SeverityBadge.vue'
import TargetAnnotations from '@/components/TargetAnnotations.vue'
import ViewState from '@/components/ViewState.vue'
import { useAnalysisView } from '@/composables/use-analysis-view'
import { formatTimestamp } from '@/services/format-time'
import { laneBars, laneMeta } from '@/services/lanes'
import { processClock, processLifetime, processTitle } from '@/services/process-graph'
import { processTarget } from '@/stores/annotations'

type SubTab = 'apis' | 'modules' | 'events'

const props = defineProps<{
  analysisId: number
  node: ProcessNode
  injectedInto: ProcessRef[]
  injectedFrom: ProcessRef[]
}>()

const NOTHING = '–'

// The process view is keyed by pid, which is what the shared loader reloads on.
const extras = useAnalysisView(
  () => props.node.pid,
  (pid) => viewsProcess({ path: { analysis_id: props.analysisId, pid } }),
)

const subTab = ref<SubTab>('apis')
const lanes = computed(() => laneBars(props.node.event_counts_by_lane))
const subTabs = computed(() => {
  const detail = extras.data.value
  return [
    { key: 'apis' as const, label: 'TOP APIS', count: detail?.top_apis.length ?? 0 },
    { key: 'modules' as const, label: 'MODULES', count: detail?.modules.length ?? 0 },
    { key: 'events' as const, label: 'EVENTS', count: detail?.event_total ?? 0 },
  ]
})
const laneStyle = (lane: string) => ({ background: `var(${laneMeta(lane).color})` })
const orDash = (value: string | number | null | undefined): string | number => value ?? NOTHING
const fullTime = (iso: string | null): string | undefined => (iso === null ? undefined : formatTimestamp(iso))
</script>

<template>
  <section class="process-details">
    <header class="process-details__header">
      <h2
        class="process-details__title text-mono"
        :title="processTitle(node)"
      >
        {{ processTitle(node) }}
      </h2>
      <FilterEventsButton
        class="process-details__show-events"
        :target="{ pid: node.pid }"
      />
      <SeverityBadge
        v-if="node.max_severity && node.detection_count > 0"
        :severity="node.max_severity"
        :count="node.detection_count"
      />
      <span
        v-else
        class="process-details__quiet text-mono text-gray"
      >no detections</span>
    </header>

    <dl class="process-details__facts">
      <div class="process-details__fact process-details__fact--wide">
        <dt>COMMAND LINE</dt>
        <dd class="process-details__long text-mono">
          {{ orDash(node.command_line) }}
        </dd>
      </div>
      <div class="process-details__fact process-details__fact--wide">
        <dt>PATH</dt>
        <dd
          class="process-details__oneline text-mono"
          :title="node.executable ?? undefined"
        >
          {{ orDash(node.executable) }}
        </dd>
      </div>
      <div class="process-details__fact">
        <dt>PID</dt>
        <dd class="text-mono">
          {{ node.pid }}
        </dd>
      </div>
      <div class="process-details__fact">
        <dt>PPID</dt>
        <dd class="text-mono">
          {{ orDash(node.ppid) }}
        </dd>
      </div>
      <div class="process-details__fact">
        <dt>INTEGRITY</dt>
        <dd class="text-mono">
          {{ orDash(node.integrity) }}
        </dd>
      </div>
      <div class="process-details__fact">
        <dt>DURATION</dt>
        <dd class="text-mono">
          {{ orDash(processLifetime(node)) }}
        </dd>
      </div>
      <div class="process-details__fact">
        <dt>START (UTC)</dt>
        <dd
          class="text-mono"
          :title="fullTime(node.start)"
        >
          {{ processClock(node.start) }}
        </dd>
      </div>
      <div class="process-details__fact">
        <dt>END (UTC)</dt>
        <dd
          class="text-mono"
          :title="fullTime(node.end)"
        >
          {{ processClock(node.end) }}
        </dd>
      </div>
      <div class="process-details__fact process-details__fact--wide">
        <dt>NETWORK HOSTS</dt>
        <dd class="text-mono">
          <template v-if="node.network_hosts.length > 0">
            <span
              v-for="host in node.network_hosts"
              :key="host"
              class="process-details__host"
            >{{ host }}</span>
          </template>
          <template v-else>
            {{ NOTHING }}
          </template>
        </dd>
      </div>
      <div
        v-if="injectedInto.length > 0"
        class="process-details__fact process-details__fact--wide"
      >
        <dt>INJECTED INTO</dt>
        <dd>
          <ProcessChip
            v-for="peer in injectedInto"
            :key="peer.pid"
            :process="peer"
          />
        </dd>
      </div>
      <div
        v-if="injectedFrom.length > 0"
        class="process-details__fact process-details__fact--wide"
      >
        <dt>INJECTED FROM</dt>
        <dd>
          <ProcessChip
            v-for="peer in injectedFrom"
            :key="peer.pid"
            :process="peer"
          />
        </dd>
      </div>
    </dl>

    <ul
      v-if="lanes.length > 0"
      class="process-details__lanes text-mono"
      aria-label="Events by lane"
    >
      <li
        v-for="bar in lanes"
        :key="bar.lane"
        class="process-details__lane"
      >
        <span
          class="process-details__mark"
          :style="laneStyle(bar.lane)"
          aria-hidden="true"
        />
        {{ bar.label }} <strong>{{ bar.count }}</strong>
      </li>
    </ul>

    <TargetAnnotations
      class="process-details__annotations"
      :target="processTarget(node.pid)"
    />

    <ViewState
      :loading="extras.loading.value"
      :error="extras.error.value"
      @retry="extras.reload"
    >
      <template v-if="extras.data.value">
        <div
          class="process-details__tabs"
          role="tablist"
          aria-label="Process activity"
        >
          <button
            v-for="tab in subTabs"
            :key="tab.key"
            type="button"
            role="tab"
            class="process-details__tab text-mono"
            :aria-selected="tab.key === subTab"
            @click="subTab = tab.key"
          >
            {{ tab.label }} {{ tab.count }}
          </button>
        </div>

        <div class="process-details__body">
          <template v-if="subTab === 'apis'">
            <p
              v-if="extras.data.value.top_apis.length === 0"
              class="text-mono text-gray"
            >
              &gt; no API calls recorded
            </p>
            <table
              v-else
              class="tt-table process-details__apis text-mono"
            >
              <tbody>
                <tr
                  v-for="api in extras.data.value.top_apis"
                  :key="api.name"
                >
                  <td>{{ api.name }}</td>
                  <td class="num">
                    {{ api.count }}
                  </td>
                </tr>
              </tbody>
            </table>
          </template>

          <template v-else-if="subTab === 'modules'">
            <p
              v-if="extras.data.value.modules.length === 0"
              class="text-mono text-gray"
            >
              &gt; no modules recorded
            </p>
            <table
              v-else
              class="tt-table process-details__modules text-mono"
            >
              <thead>
                <tr>
                  <th>NAME</th>
                  <th>BASE ADDRESS</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="module in extras.data.value.modules"
                  :key="`${module.name}@${module.base_address}`"
                >
                  <td>
                    {{ module.name }}
                    <span
                      v-if="module.path"
                      class="process-details__path text-gray"
                    >{{ module.path }}</span>
                  </td>
                  <td>{{ module.base_address }}</td>
                </tr>
              </tbody>
            </table>
          </template>

          <template v-else>
            <p
              v-if="extras.data.value.events.length === 0"
              class="text-mono text-gray"
            >
              &gt; no events recorded
            </p>
            <template v-else>
              <p class="process-details__note text-mono text-gray">
                {{ extras.data.value.events.length }} of {{ extras.data.value.event_total }}, newest first
              </p>
              <ul class="process-details__events">
                <li
                  v-for="event in extras.data.value.events"
                  :key="event.event_id"
                >
                  <span class="process-details__event-head text-mono text-gray">
                    <span
                      class="process-details__mark"
                      :style="laneStyle(event.lane)"
                      aria-hidden="true"
                    />
                    <span>{{ laneMeta(event.lane).label }} · {{ event.action }} · {{ formatTimestamp(event.time) }}</span>
                  </span>
                  <span class="process-details__summary">{{ event.summary }}</span>
                </li>
              </ul>
            </template>
          </template>
        </div>
      </template>
    </ViewState>
  </section>
</template>

<style scoped>
.process-details {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: var(--spacing-sm) var(--spacing-md);
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
  overflow-y: auto;
}

.process-details__header {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-sm);
}

.process-details__title {
  min-width: 0;
  margin: 0;
  font-size: 1rem;
  font-weight: bold;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.process-details__show-events {
  margin-left: auto;
  color: var(--blue-primary);
}

.process-details__quiet {
  flex: none;
  font-size: 0.7rem;
}

.process-details__facts {
  display: grid;
  flex: none;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--spacing-xs) var(--spacing-sm);
  margin: 0;
}

.process-details__fact {
  min-width: 0;
}

.process-details__fact--wide {
  grid-column: 1 / -1;
}

.process-details__fact dt {
  color: var(--blue-primary);
  font-family: var(--font-mono);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
  line-height: 1.4;
}

.process-details__fact dd {
  margin: 0;
  font-size: 0.8rem;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.process-details__long {
  max-height: 2.8em;
  overflow-y: auto;
  white-space: pre-wrap;
}

.process-details__oneline {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.process-details__host {
  display: block;
}

.process-details__lanes {
  display: flex;
  flex: none;
  flex-wrap: wrap;
  gap: var(--spacing-xs) var(--spacing-sm);
  margin: var(--spacing-sm) 0 0;
  padding: 0;
  font-size: 0.6rem;
  letter-spacing: 0;
  list-style: none;
}

.process-details__lane {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-xs);
  white-space: nowrap;
}

.process-details__mark {
  display: inline-block;
  width: 8px;
  height: 8px;
  flex: none;
}

.process-details__annotations {
  flex: none;
  margin-top: var(--spacing-sm);
  padding-top: var(--spacing-sm);
  border-top: 1px solid var(--border-subtle);
}

.process-details__tabs {
  display: flex;
  flex: none;
  flex-wrap: wrap;
  margin-top: var(--spacing-sm);
  border-bottom: 2px solid var(--border-primary);
}

.process-details__tab {
  padding: var(--spacing-xs) var(--spacing-sm);
  margin-bottom: -2px;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-gray);
  font-size: 0.65rem;
  letter-spacing: 1px;
  cursor: pointer;
}

.process-details__tab:hover {
  color: var(--blue-hover);
}

.process-details__tab[aria-selected='true'] {
  border-bottom-color: var(--blue-primary);
  color: var(--blue-primary);
}

.process-details__body {
  flex: 1 1 0;
  min-height: 8rem;
  padding-top: var(--spacing-sm);
  overflow: auto;
}

@media (max-width: 900px) {
  .process-details__body {
    flex: none;
    height: 22rem;
  }
}

.process-details__body :deep(.tt-table td) {
  padding: var(--spacing-xs) var(--spacing-sm);
}

.process-details__body :deep(.tt-table th) {
  padding: var(--spacing-xs) var(--spacing-sm);
}

.process-details__path {
  display: block;
  white-space: normal;
  overflow-wrap: anywhere;
}

.process-details__note {
  margin: 0 0 var(--spacing-sm);
  font-size: 0.7rem;
}

.process-details__events {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  margin: 0;
  padding: 0;
  list-style: none;
}

.process-details__events li {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.process-details__event-head {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-xs);
  font-size: 0.7rem;
}

.process-details__summary {
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}
</style>
