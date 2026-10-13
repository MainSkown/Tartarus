<script setup lang="ts">
import { computed } from 'vue'
import { viewsProcess, type ProcessNode, type ProcessRef } from '@/api'
import LaneBars from '@/components/LaneBars.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import SeverityBadge from '@/components/SeverityBadge.vue'
import ViewState from '@/components/ViewState.vue'
import { useAnalysisView } from '@/composables/use-analysis-view'
import { formatTimestamp } from '@/services/format-time'
import { laneBars, laneMeta } from '@/services/lanes'
import { processLifetime, processTitle } from '@/services/process-graph'

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

const lanes = computed(() => laneBars(props.node.event_counts_by_lane))
const hasInjection = computed(() => props.injectedInto.length > 0 || props.injectedFrom.length > 0)
const laneStyle = (lane: string) => ({ background: `var(${laneMeta(lane).color})` })
const orDash = (value: string | number | null | undefined): string | number => value ?? NOTHING
const time = (iso: string | null): string => (iso === null ? NOTHING : formatTimestamp(iso))
</script>

<template>
  <section class="process-details">
    <h2 class="process-details__title text-mono">
      {{ processTitle(node) }}
    </h2>

    <dl class="process-details__fields">
      <dt>COMMAND LINE</dt>
      <dd class="process-details__command text-mono">
        {{ orDash(node.command_line) }}
      </dd>
      <dt>PATH</dt>
      <dd class="text-mono">
        {{ orDash(node.executable) }}
      </dd>
      <dt>PID</dt>
      <dd class="text-mono">
        {{ node.pid }}
      </dd>
      <dt>PPID</dt>
      <dd class="text-mono">
        {{ orDash(node.ppid) }}
      </dd>
      <dt>INTEGRITY</dt>
      <dd class="text-mono">
        {{ orDash(node.integrity) }}
      </dd>
      <dt>START</dt>
      <dd class="text-mono">
        {{ time(node.start) }}
      </dd>
      <dt>END</dt>
      <dd class="text-mono">
        {{ time(node.end) }}
      </dd>
      <dt>DURATION</dt>
      <dd class="text-mono">
        {{ orDash(processLifetime(node)) }}
      </dd>
      <dt>DETECTIONS</dt>
      <dd>
        <SeverityBadge
          v-if="node.max_severity && node.detection_count > 0"
          :severity="node.max_severity"
          :count="node.detection_count"
        />
        <span
          v-else
          class="text-mono text-gray"
        >none</span>
      </dd>
      <dt>NETWORK HOSTS</dt>
      <dd>
        <ul
          v-if="node.network_hosts.length > 0"
          class="process-details__list text-mono"
        >
          <li
            v-for="host in node.network_hosts"
            :key="host"
          >
            {{ host }}
          </li>
        </ul>
        <span
          v-else
          class="text-mono"
        >{{ NOTHING }}</span>
      </dd>
      <template v-if="hasInjection">
        <template v-if="injectedInto.length > 0">
          <dt>INJECTED INTO</dt>
          <dd>
            <ul class="process-details__list">
              <li
                v-for="peer in injectedInto"
                :key="peer.pid"
              >
                <ProcessChip :process="peer" />
              </li>
            </ul>
          </dd>
        </template>
        <template v-if="injectedFrom.length > 0">
          <dt>INJECTED FROM</dt>
          <dd>
            <ul class="process-details__list">
              <li
                v-for="peer in injectedFrom"
                :key="peer.pid"
              >
                <ProcessChip :process="peer" />
              </li>
            </ul>
          </dd>
        </template>
      </template>
      <dt>EVENTS</dt>
      <dd>
        <LaneBars
          v-if="lanes.length > 0"
          :bars="lanes"
        />
        <span
          v-else
          class="text-mono"
        >{{ NOTHING }}</span>
      </dd>
    </dl>

    <ViewState
      :loading="extras.loading.value"
      :error="extras.error.value"
      @retry="extras.reload"
    >
      <template v-if="extras.data.value">
        <q-expansion-item
          class="process-details__modules"
          dense
          :label="`MODULES  ${extras.data.value.modules.length}`"
        >
          <p
            v-if="extras.data.value.modules.length === 0"
            class="text-mono text-gray"
          >
            &gt; no modules recorded
          </p>
          <div
            v-else
            class="tt-table-scroll"
          >
            <table class="tt-table text-mono">
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
          </div>
        </q-expansion-item>

        <template v-if="extras.data.value.top_apis.length > 0">
          <h3 class="process-details__heading text-mono">
            TOP APIS
          </h3>
          <div class="tt-table-scroll">
            <table class="tt-table process-details__apis text-mono">
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
          </div>
        </template>

        <h3 class="process-details__heading text-mono">
          RECENT EVENTS
          <span
            v-if="extras.data.value.events.length > 0"
            class="text-gray"
          >{{ extras.data.value.events.length }} of {{ extras.data.value.event_total }}</span>
        </h3>
        <p
          v-if="extras.data.value.events.length === 0"
          class="text-mono text-gray"
        >
          &gt; no events recorded
        </p>
        <ul
          v-else
          class="process-details__events"
        >
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
    </ViewState>
  </section>
</template>

<style scoped>
.process-details {
  min-width: 0;
  padding: var(--spacing-md);
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
}

.process-details__title {
  margin: 0 0 var(--spacing-md);
  font-size: 1rem;
  font-weight: bold;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.process-details__fields {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: var(--spacing-sm) var(--spacing-md);
  margin: 0;
}

.process-details__fields dt {
  color: var(--blue-primary);
  font-family: var(--font-mono);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
  line-height: 1.6;
}

.process-details__fields dd {
  min-width: 0;
  margin: 0;
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.process-details__command {
  white-space: pre-wrap;
}

.process-details__list,
.process-details__events {
  margin: 0;
  padding: 0;
  list-style: none;
}

.process-details__mark {
  display: inline-block;
  width: 8px;
  height: 8px;
  flex: none;
}

.process-details__heading {
  margin: var(--spacing-md) 0 var(--spacing-sm);
  color: var(--blue-primary);
  font-size: 0.65rem;
  line-height: 1.2;
  letter-spacing: 1px;
}

.process-details__modules {
  margin-top: var(--spacing-md);
}

.process-details__modules :deep(.q-item) {
  min-height: 0;
  padding: 0;
}

.process-details__modules :deep(.q-item__section--main) {
  color: var(--blue-primary);
  font-size: 0.65rem;
  letter-spacing: 1px;
}

.process-details__path {
  display: block;
  white-space: normal;
  overflow-wrap: anywhere;
}

.process-details__events {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
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
