<script setup lang="ts">
import StatusBadge from '@/components/StatusBadge.vue'
import { useActivityAge } from '@/composables/use-activity-age'
import { t } from '@/i18n'
import { buildKindLabel, type BuildPhase } from '@/services/guest-build'

const props = defineProps<{
  guest: string
  kind: string
  phase: BuildPhase
  percent: number
  message: string
  /** The quiet way back, left out where the verdict offers [OPEN GUEST VM]. */
  backLink: boolean
  /** What the running step is, in the profile's own words. */
  description?: string | null
  /** When the running step last logged or moved its progress (ISO). */
  lastActivity?: string | null
}>()

const activity = useActivityAge(() => props.lastActivity)
</script>

<template>
  <header
    class="build-header"
    data-build="header"
  >
    <div class="build-header__title">
      <span
        class="build-header__kind text-mono"
        data-build="kind"
      >{{ buildKindLabel(kind) }}</span>
      <h1 class="build-header__guest text-mono">
        <router-link
          to="/guest"
          :title="guest"
        >
          {{ guest }}
        </router-link>
      </h1>
      <StatusBadge :build-phase="phase" />
      <div class="build-header__actions">
        <q-btn
          v-if="backLink"
          flat
          dense
          square
          no-caps
          :label="t('guests.action.backToGuestVm')"
          class="build-header__back text-mono"
          to="/guest"
        />
        <slot name="actions" />
      </div>
    </div>
    <progress
      :value="percent"
      max="100"
      :aria-label="t('guests.buildHeader.progressLabel', { guest, kind: buildKindLabel(kind).toLowerCase() })"
    />
    <p class="build-header__message text-mono text-gray">
      <span data-build="percent">{{ percent }}%</span>
      <span data-build="message">{{ message }}</span>
      <span
        v-if="activity"
        class="build-header__activity"
        :class="{ 'build-header__activity--stale': activity.stale }"
        :data-stale="String(activity.stale)"
        data-build="activity"
      >
        <q-icon
          v-if="activity.stale"
          name="warning"
          size="14px"
          aria-hidden="true"
        />{{ activity.text }}</span>
    </p>
    <p
      v-if="description"
      class="build-header__description text-mono"
      data-build="description"
    >
      {{ description }}
    </p>
  </header>
</template>

<style scoped>
.build-header {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  min-width: 0;
}

.build-header__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-sm);
  min-width: 0;
}

.build-header__kind {
  padding: 1px 6px;
  border: 1px solid var(--blue-primary);
  color: var(--blue-primary);
  font-size: 0.75rem;
  letter-spacing: 1px;
}

.build-header__guest {
  flex: 0 1 auto;
  min-width: 0;
  margin: 0;
  overflow: hidden;
  font-size: 1.25rem;
  font-weight: 600;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.build-header__guest a {
  color: var(--text-white);
  text-decoration: none;
}

.build-header__guest a:hover {
  color: var(--blue-light);
}

.build-header__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-sm);
  min-width: 0;
  margin-left: auto;
}

.build-header__back {
  color: var(--text-gray);
  font-size: 0.75rem;
}

.build-header__message {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--spacing-xs) var(--spacing-sm);
  margin: 0;
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.build-header__message [data-build='percent'] {
  flex: none;
}

.build-header__message [data-build='message'] {
  flex: 1 1 14rem;
  min-width: 0;
}

.build-header__activity {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: var(--spacing-xs);
  margin-left: auto;
  white-space: nowrap;
}

.build-header__activity--stale {
  color: var(--status-medium);
  white-space: normal;
}

.build-header__description {
  max-width: 72ch;
  margin: 0;
  color: var(--text-gray);
  font-size: 0.8rem;
  line-height: 1.45;
}
</style>
