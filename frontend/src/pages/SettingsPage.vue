<script setup lang="ts">
import { onMounted, reactive, ref, toRef } from 'vue'
import { Notify } from 'quasar'
import { settingsRead, settingsReplace } from '@/api'
import type { SettingsBody } from '@/api'
import { t } from '@/i18n'
import { useDefaultGuestField } from '@/composables/use-default-guest-field'
import { BUILT_ROUTES } from '@/services/routes'
import { validationIssues } from '@/services/validation-errors'

type LoadStatus = 'loading' | 'loaded' | 'failed'

const status = ref<LoadStatus>('loading')
const saving = ref(false)
const form = reactive<SettingsBody>({})
// Keyed by form field name: the last segment of each 422 `location`. The server owns the
// rules; this only shows each message on the input it names.
const fieldErrors = ref<Record<string, string>>({})
const defaultGuest = toRef(form, 'default_guest')
const guestField = useDefaultGuestField(defaultGuest)

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
  Notify.create({ type: 'tt-success', message: t('settings.saved') })
}

onMounted(() => {
  void loadSettings()
  void guestField.load()
})
</script>

<template>
  <div class="settings-page">
    <h1 class="section-title text-mono">
      {{ t('settings.title') }}
    </h1>

    <div
      v-if="status === 'loading'"
      class="page-state"
    >
      <span
        class="loader"
        role="status"
        :aria-label="t('settings.loading')"
      />
    </div>

    <div
      v-else-if="status === 'failed'"
      class="page-state text-mono"
    >
      <p class="text-gray">
        {{ t('settings.loadFailed') }}
      </p>
      <q-btn
        outline
        square
        :label="t('common.retry')"
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
        <span class="field-title text-mono">{{ t('settings.route.title') }}</span>
        <div
          class="radio-group"
          role="radiogroup"
          :aria-label="t('settings.route.group')"
        >
          <template
            v-for="route in BUILT_ROUTES"
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
          class="field-error"
          role="alert"
        >
          {{ fieldErrors.default_route }}
        </p>
      </div>

      <div class="settings-field">
        <q-select
          v-model="form.default_guest"
          :options="guestField.options.value"
          :display-value="guestField.displayValue.value"
          outlined
          dense
          hide-bottom-space
          emit-value
          map-options
          :label="t('settings.guest')"
          :error="Boolean(fieldErrors.default_guest)"
          :error-message="fieldErrors.default_guest"
          class="settings-input text-mono"
        />
        <p
          v-if="guestField.note.value"
          class="guest-note text-mono"
          role="status"
        >
          {{ guestField.note.value }}
        </p>
      </div>

      <!-- hide-bottom-space on all three inputs: without it Quasar reserves 20px under each
           for an error message, making gaps uneven. An error now pushes the form down instead. -->
      <q-input
        :model-value="form.default_timeout"
        outlined
        dense
        hide-bottom-space
        type="number"
        :label="t('settings.timeout.label')"
        :suffix="t('settings.timeout.unit')"
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
          >{{ t('settings.interactive') }}</label>
        </div>
        <p
          v-if="fieldErrors.default_interactive"
          class="field-error"
          role="alert"
        >
          {{ fieldErrors.default_interactive }}
        </p>
      </div>

      <q-input
        :model-value="form.disk_warn_gb"
        outlined
        dense
        hide-bottom-space
        type="number"
        :label="t('settings.diskWarn')"
        :error="Boolean(fieldErrors.disk_warn_gb)"
        :error-message="fieldErrors.disk_warn_gb"
        class="settings-input"
        @update:model-value="(value) => (form.disk_warn_gb = Number(value))"
      />

      <q-input
        :model-value="form.disk_block_gb"
        outlined
        dense
        hide-bottom-space
        type="number"
        :label="t('settings.diskBlock')"
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
          :label="t('settings.save')"
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
  /* Quasar's typography gives h1 a 6rem line-height, which shrinking the font doesn't undo. */
  line-height: 1.2;
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
  max-width: 100%;
  flex-wrap: wrap;
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

.guest-note {
  margin: 0;
  color: var(--status-medium);
  font-size: 0.75rem;
  overflow-wrap: anywhere;
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
