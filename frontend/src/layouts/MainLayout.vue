<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import HealthDot from '@/components/HealthDot.vue'
import { useReportNotices } from '@/composables/use-report-notices'
import { useGuestBlockReason } from '@/services/guest-gate'
import { openSubmitDialog } from '@/services/submit-dialog'
import { useSystemStore } from '@/stores/system'

interface NavItem {
  to: string
  label: string
  iconOutlined: string
  iconFilled: string
}

// Iconography: Material Icons outlined by default, filled for the active state (design
// system "Iconography").
const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Dashboard', iconOutlined: 'o_dashboard', iconFilled: 'dashboard' },
  { to: '/rules', label: 'Rules', iconOutlined: 'o_policy', iconFilled: 'policy' },
  { to: '/guest', label: 'Guest VM', iconOutlined: 'o_dns', iconFilled: 'dns' },
  { to: '/settings', label: 'Settings', iconOutlined: 'o_settings', iconFilled: 'settings' },
]

const system = useSystemStore()
const route = useRoute()
const drawerExpanded = ref(false)

function isActive(path: string): boolean {
  return path === '/' ? route.path === '/' : route.path.startsWith(path)
}

// ws.ts only ever reports "connecting" on the very first connect() attempt (attempt === 0);
// every later drop goes straight to "reconnecting". Hiding the bar for "connecting" hides it
// during that one brief initial handshake without ever masking a real outage, so nothing
// else needs to special-case first load.
const showReconnectBar = computed(
  () => system.connectionState === 'reconnecting' || system.connectionState === 'closed',
)

const storeSubStatuses = computed(() => {
  const health = system.health
  if (!health) return []
  return [
    { label: 'Postgres', status: health.postgres.status, message: health.postgres.message },
    { label: 'OpenSearch', status: health.opensearch.status, message: health.opensearch.message },
  ]
})

const submitDisabledReason = useGuestBlockReason()
useReportNotices()
</script>

<template>
  <q-layout view="hHh LpR fFf">
    <q-header class="app-header">
      <!-- Inside the header, not above it: the header is fixed, so anything in the page flow
           above it is painted over. Quasar measures the header, so the page shifts to fit. -->
      <div
        v-if="showReconnectBar"
        class="reconnect-bar text-mono"
      >
        Reconnecting…
      </div>
      <q-toolbar class="app-toolbar">
        <div class="wordmark text-mono">
          TARTARUS
        </div>

        <div class="health-dots">
          <HealthDot
            label="CAPE"
            :status="system.health?.cape.status ?? 'down'"
            :message="system.health?.cape.message"
          />
          <HealthDot
            label="Guest"
            :status="system.health?.guest.status ?? 'down'"
            :message="system.health?.guest.message"
          />
          <HealthDot
            label="Store"
            :status="system.storeStatus ?? 'down'"
            :sub-statuses="storeSubStatuses"
          />
        </div>

        <!-- Queue count, disk usage and the "LIVE #42 01:12" chip (gui spec "App shell") are
             deferred: there is no queue/job backend and no disk-usage endpoint yet in this
             phase. They are not faked here; they arrive with the milestones that back them. -->

        <q-space />

        <div
          class="submit-wrapper"
          role="group"
          :aria-label="submitDisabledReason"
        >
          <q-btn
            outline
            square
            :disable="submitDisabledReason !== undefined"
            label="+ SUBMIT"
            class="submit-btn text-mono"
            @click="openSubmitDialog"
          />
          <q-tooltip v-if="submitDisabledReason">
            {{ submitDisabledReason }}
          </q-tooltip>
        </div>
      </q-toolbar>
    </q-header>

    <q-drawer
      :model-value="true"
      behavior="desktop"
      :mini="!drawerExpanded"
      :width="200"
      :mini-width="56"
      bordered
      class="nav-drawer"
      @mouseenter="drawerExpanded = true"
      @mouseleave="drawerExpanded = false"
    >
      <q-list class="nav-list">
        <q-item
          v-for="item in NAV_ITEMS"
          :key="item.to"
          clickable
          :to="item.to"
          :active="isActive(item.to)"
          class="nav-item"
        >
          <q-item-section avatar>
            <q-icon
              :name="isActive(item.to) ? item.iconFilled : item.iconOutlined"
              size="24px"
            />
          </q-item-section>
          <q-item-section v-if="drawerExpanded">
            {{ item.label }}
          </q-item-section>
          <q-tooltip
            v-if="!drawerExpanded"
            anchor="center right"
            self="center left"
          >
            {{ item.label }}
          </q-tooltip>
        </q-item>
      </q-list>
    </q-drawer>

    <q-page-container>
      <router-view />
    </q-page-container>
  </q-layout>
</template>

<style scoped>
.reconnect-bar {
  background: var(--status-medium);
  color: var(--black);
  text-align: center;
  font-size: 0.8rem;
  letter-spacing: 1px;
  padding: 2px 0;
}

.app-header {
  background: var(--black);
  border-bottom: 2px solid var(--border-primary);
}

.app-toolbar {
  height: 48px;
  min-height: 48px;
  gap: var(--spacing-lg);
  padding-right: var(--spacing-lg);
}

.wordmark {
  color: var(--blue-primary);
  letter-spacing: 4px;
  font-weight: 600;
}

.health-dots {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
}

.submit-wrapper {
  display: inline-flex;
}

.submit-btn {
  color: var(--blue-primary);
}

.nav-list {
  padding-top: var(--spacing-sm);
}

.nav-item {
  color: var(--text-gray);
}
</style>
