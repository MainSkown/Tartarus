<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Notify } from 'quasar'
import { settingsRead, settingsReplace } from '@/api'
import type { Route, SettingsBody } from '@/api'
import { validationIssues } from '@/services/validation-errors'

const ROUTES: Route[] = ['none', 'drop', 'internet', 'inetsim', 'tor', 'vpn', 'wireguard', 'socks5']

type LoadStatus = 'loading' | 'loaded' | 'failed'

const status = ref<LoadStatus>('loading')
const saving = ref(false)
const form = reactive<SettingsBody>({})
// Keyed by form field name: the last segment of each 422 `location`. The server owns the
// rules; this only shows each message on the input it names.
const fieldErrors = ref<Record<string, string>>({})

async function loadSettings(): Promise<void> {
  status.value = 'loading'
  const { data, error } = await settingsRead()
  if (error || !data) {
    status.value = 'failed'
    return
  }
  Object.assign(form, data)
  status.value = 'loaded'
}

async function saveSettings(): Promise<void> {
  saving.value = true
  fieldErrors.value = {}
  const { data, error } = await settingsReplace({ body: { ...form } })
  saving.value = false
  if (error) {
    fieldErrors.value = Object.fromEntries(validationIssues(error).map(({ field, message }) => [field, message]))
    return
  }
  if (data) Object.assign(form, data)
  Notify.create({ type: 'tt-success', message: 'Settings saved' })
}

onMounted(loadSettings)
</script>

<template>
  <div class="settings-page">
    <h1 class="section-title text-mono">
      DEFAULTS
    </h1>

    <div
      v-if="status === 'loading'"
      class="page-state"
    >
      <span
        class="loader"
        role="status"
        aria-label="Loading settings"
      />
    </div>

    <div
      v-else-if="status === 'failed'"
      class="page-state text-mono"
    >
      <p class="text-gray">
        &gt; failed to load settings
      </p>
      <q-btn
        outline
        square
        label="[RETRY]"
        class="retry-btn text-mono"
        @click="loadSettings"
      />
    </div>

    <form
      v-else
      class="settings-form"
      @submit.prevent="saveSettings"
    >
      <div class="settings-field">
        <span class="field-title text-mono">DEFAULT ROUTE</span>
        <div
          class="radio-group"
          role="radiogroup"
          aria-label="Default route"
        >
          <template
            v-for="route in ROUTES"
            :key="route"
          >
            <input
              :id="`route-${route}`"
              v-model="form.default_route"
              type="radio"
              name="default-route"
              class="radio-input"
              :value="route"
            >
            <label
              :for="`route-${route}`"
              class="radio-label text-mono"
            >{{ route }}</label>
          </template>
        </div>
        <p
          v-if="fieldErrors.default_route"
          class="field-error text-mono"
          role="alert"
        >
          {{ fieldErrors.default_route }}
        </p>
      </div>

      <q-input
        :model-value="form.default_timeout"
        outlined
        dense
        type="number"
        label="DEFAULT TIMEOUT"
        suffix="s"
        :error="Boolean(fieldErrors.default_timeout)"
        :error-message="fieldErrors.default_timeout"
        class="settings-input"
        @update:model-value="(value) => (form.default_timeout = Number(value))"
      />

      <div class="settings-field">
        <div class="checkbox-row">
          <input
            id="default-interactive"
            v-model="form.default_interactive"
            type="checkbox"
            class="checkbox-input"
          >
          <label
            for="default-interactive"
            class="field-title text-mono"
          >DEFAULT INTERACTIVE</label>
        </div>
        <p
          v-if="fieldErrors.default_interactive"
          class="field-error text-mono"
          role="alert"
        >
          {{ fieldErrors.default_interactive }}
        </p>
      </div>

      <q-input
        :model-value="form.disk_warn_gb"
        outlined
        dense
        type="number"
        label="DISK WARN (GB)"
        :error="Boolean(fieldErrors.disk_warn_gb)"
        :error-message="fieldErrors.disk_warn_gb"
        class="settings-input"
        @update:model-value="(value) => (form.disk_warn_gb = Number(value))"
      />

      <q-input
        :model-value="form.disk_block_gb"
        outlined
        dense
        type="number"
        label="DISK BLOCK (GB)"
        :error="Boolean(fieldErrors.disk_block_gb)"
        :error-message="fieldErrors.disk_block_gb"
        class="settings-input"
        @update:model-value="(value) => (form.disk_block_gb = Number(value))"
      />

      <div class="form-actions">
        <q-btn
          outline
          square
          type="submit"
          label="[SAVE]"
          class="save-btn text-mono"
          :disable="saving"
        />
      </div>
    </form>

    <!-- Network routes (read-only list, how to add a tunnel in .env) and About (versions,
         doc links, safety reminder) are deferred: they need backend data this phase does not
         expose yet. Like the header's deferred items, they are not faked here. -->
  </div>
</template>

<style scoped>
.settings-page {
  padding: var(--spacing-lg);
  max-width: 480px;
}

.section-title {
  color: var(--blue-primary);
  font-size: 0.9rem;
  letter-spacing: 2px;
  margin: 0 0 var(--spacing-lg);
}

.page-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-md);
  padding: var(--spacing-xl) 0;
}

.settings-form {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
}

.settings-field {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.field-title {
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.radio-group {
  position: relative;
  align-self: flex-start;
}

.radio-label {
  text-transform: uppercase;
  letter-spacing: 1px;
  font-size: 0.8rem;
}

.checkbox-row {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.field-error {
  margin: 0;
  color: var(--status-critical);
  font-size: 0.75rem;
}

.form-actions {
  display: flex;
}

.save-btn {
  color: var(--blue-primary);
}
</style>
