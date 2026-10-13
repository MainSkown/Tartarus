<script setup lang="ts">
import { computed, onMounted, ref, shallowRef } from 'vue'
import { useDialogPluginComponent } from 'quasar'
import { useRouter } from 'vue-router'
import { settingsRead } from '@/api'
import type { Route } from '@/api'
import { sha256Hex } from '@/services/file-hash'
import { formatFileSize } from '@/services/file-size'
import { useGuestBlockReason } from '@/services/guest-gate'
import type { ValidationIssue } from '@/services/validation-errors'
import { SubmissionRejected, useAnalysesStore, type SubmitOptions } from '@/stores/analyses'

defineEmits([...useDialogPluginComponent.emits])
const { dialogRef, onDialogHide, onDialogOK, onDialogCancel } = useDialogPluginComponent()

// The built subset of Route: VPN, WireGuard and SOCKS5 appear only once configured (gui spec).
const ROUTES: Route[] = ['inetsim', 'none', 'drop', 'internet']
const TIMEOUT_MIN_SECONDS = 60
const TIMEOUT_MAX_SECONDS = 1200
const TIMEOUT_ERROR = `Timeout must be a whole number from ${TIMEOUT_MIN_SECONDS} to ${TIMEOUT_MAX_SECONDS} seconds`
const FORM_FIELDS = ['file', 'route', 'timeout', 'package'] as const
type FormField = (typeof FORM_FIELDS)[number]

const analyses = useAnalysesStore()
const router = useRouter()
const guestBlockReason = useGuestBlockReason()

const file = shallowRef<File>()
const hash = ref<string>()
const route = ref<Route>('inetsim')
const timeoutText = ref('180')
const packageName = ref('')

const dragOver = ref(false)
const dropError = ref<string>()
const submitting = ref(false)
const fieldErrors = ref<Partial<Record<FormField, string>>>({})
const errorBanner = ref<string>()
const fileInput = ref<HTMLInputElement>()

const timeoutError = computed(() => {
  const seconds = Number(timeoutText.value)
  const valid = timeoutText.value.trim() !== '' && Number.isInteger(seconds)
  return valid && seconds >= TIMEOUT_MIN_SECONDS && seconds <= TIMEOUT_MAX_SECONDS ? undefined : TIMEOUT_ERROR
})

const blockReason = computed(() => guestBlockReason.value ?? (file.value ? undefined : 'Choose a sample to analyse'))
const canSubmit = computed(() => !blockReason.value && !timeoutError.value && !submitting.value)

const submitOptions = computed<SubmitOptions>(() => {
  const trimmedPackage = packageName.value.trim()
  return {
    route: route.value,
    timeout: Number(timeoutText.value),
    ...(trimmedPackage ? { package: trimmedPackage } : {}),
  }
})

async function applySettingsDefaults(): Promise<void> {
  const { data } = await settingsRead()
  if (data?.default_route && ROUTES.includes(data.default_route)) route.value = data.default_route
  const defaultTimeout = data?.default_timeout
  if (defaultTimeout && defaultTimeout >= TIMEOUT_MIN_SECONDS && defaultTimeout <= TIMEOUT_MAX_SECONDS) {
    timeoutText.value = String(defaultTimeout)
  }
}

async function chooseFile(chosen: File): Promise<void> {
  file.value = chosen
  hash.value = undefined
  dropError.value = undefined
  fieldErrors.value = {}
  errorBanner.value = undefined
  const digest = await sha256Hex(chosen)
  // A slower hash of an earlier choice must not label the file chosen since.
  if (file.value === chosen) hash.value = digest
}

function onFileInput(event: Event): void {
  const chosen = (event.target as HTMLInputElement).files?.[0]
  if (chosen) void chooseFile(chosen)
}

function onDrop(event: DragEvent): void {
  dragOver.value = false
  const dropped = event.dataTransfer?.files
  if (!dropped?.length) return
  if (dropped.length > 1) {
    dropError.value = 'Drop one file at a time'
    return
  }
  void chooseFile(dropped[0]!)
}

function showRejection(rejection: SubmissionRejected): void {
  const unplaced: ValidationIssue[] = []
  const placed: Partial<Record<FormField, string>> = {}
  for (const issue of rejection.issues) {
    const field = FORM_FIELDS.find((name) => name === issue.field)
    if (field) placed[field] ??= issue.message
    else unplaced.push(issue)
  }
  fieldErrors.value = placed
  const hasUnplaced = unplaced.length > 0
  const noFieldNamed = rejection.issues.length === 0
  if (hasUnplaced) errorBanner.value = unplaced.map((issue) => issue.message).join('; ')
  else if (noFieldNamed) errorBanner.value = rejection.message
}

async function submit(): Promise<void> {
  if (!canSubmit.value || !file.value) return
  submitting.value = true
  fieldErrors.value = {}
  errorBanner.value = undefined
  try {
    const analysis = await analyses.submit(file.value, submitOptions.value)
    onDialogOK(analysis)
    void router.push({ name: 'analysis-workspace', params: { id: analysis.id } })
  } catch (error) {
    if (error instanceof SubmissionRejected) showRejection(error)
    else errorBanner.value = 'Could not reach the backend.'
  } finally {
    submitting.value = false
  }
}

onMounted(applySettingsDefaults)
</script>

<template>
  <q-dialog
    ref="dialogRef"
    :persistent="submitting"
    @hide="onDialogHide"
  >
    <q-card class="submit-dialog">
      <form
        class="submit-form"
        @submit.prevent="submit"
      >
        <h2 class="dialog-title text-mono">
          SUBMIT SAMPLE
        </h2>

        <div class="form-field">
          <div
            class="drop-zone"
            :class="{ 'drop-zone--over': dragOver }"
            role="button"
            tabindex="0"
            @click="fileInput?.click()"
            @keydown.enter.prevent="fileInput?.click()"
            @keydown.space.prevent="fileInput?.click()"
            @dragover.prevent="dragOver = true"
            @dragleave="dragOver = false"
            @drop.prevent="onDrop"
          >
            <template v-if="file">
              <span
                class="file-name text-mono"
                :title="file.name"
              >{{ file.name }}</span>
              <span class="file-details text-mono text-gray">
                <span class="file-size">{{ formatFileSize(file.size) }}</span>
                <span
                  class="file-hash"
                  :title="hash"
                >sha256 {{ hash ?? 'hashing…' }}</span>
              </span>
            </template>
            <span
              v-else
              class="drop-hint text-mono text-gray"
            >drop file here · or click to browse</span>
          </div>
          <input
            ref="fileInput"
            type="file"
            class="file-input"
            tabindex="-1"
            aria-label="Sample file"
            @change="onFileInput"
          >
          <p
            v-if="dropError"
            class="field-error drop-error"
            role="alert"
          >
            {{ dropError }}
          </p>
          <p
            v-if="fieldErrors.file"
            class="field-error file-error"
            role="alert"
          >
            {{ fieldErrors.file }}
          </p>
        </div>

        <div class="form-field">
          <span class="field-title text-mono">NETWORK</span>
          <div
            class="radio-group"
            role="radiogroup"
            aria-label="Network route"
          >
            <template
              v-for="option in ROUTES"
              :key="option"
            >
              <input
                :id="`route-${option}`"
                v-model="route"
                type="radio"
                name="route"
                class="radio-input"
                :value="option"
                :disabled="submitting"
              >
              <label
                :for="`route-${option}`"
                class="radio-label text-mono"
              >{{ option }}</label>
            </template>
          </div>
          <p
            v-if="route === 'internet'"
            class="internet-warning"
            role="alert"
          >
            Sample will reach the real internet from this host's public IP.
          </p>
          <p
            v-if="fieldErrors.route"
            class="field-error"
            role="alert"
          >
            {{ fieldErrors.route }}
          </p>
        </div>

        <div class="option-row">
          <q-input
            v-model="timeoutText"
            outlined
            dense
            hide-bottom-space
            type="number"
            label="TIMEOUT"
            suffix="s"
            :disable="submitting"
            :error="Boolean(timeoutError ?? fieldErrors.timeout)"
            :error-message="timeoutError ?? fieldErrors.timeout"
            class="timeout-input"
          />
          <q-input
            v-model="packageName"
            outlined
            dense
            hide-bottom-space
            label="PACKAGE"
            placeholder="auto"
            :disable="submitting"
            :error="Boolean(fieldErrors.package)"
            :error-message="fieldErrors.package"
            class="package-input"
          />
        </div>

        <p
          v-if="errorBanner"
          class="error-banner text-mono"
          role="alert"
        >
          {{ errorBanner }}
        </p>

        <div class="form-actions">
          <span
            v-if="blockReason"
            class="submit-reason text-mono text-gray"
          >{{ blockReason }}</span>
          <q-space />
          <q-btn
            flat
            square
            label="CANCEL"
            class="cancel-btn text-mono"
            :disable="submitting"
            @click="onDialogCancel"
          />
          <q-btn
            outline
            square
            type="submit"
            label="▶ DETONATE"
            class="submit-btn text-mono"
            :disable="!canSubmit"
            :loading="submitting"
          />
        </div>
      </form>
    </q-card>
  </q-dialog>
</template>

<style scoped>
.submit-dialog {
  width: 560px;
  max-width: 94vw;
}

.submit-form {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
  padding: var(--spacing-lg);
}

.dialog-title {
  margin: 0;
  color: var(--blue-primary);
  font-size: 0.9rem;
  line-height: 1.2;
  letter-spacing: 2px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  /* Lets the truncating file name shrink instead of widening the dialog. */
  min-width: 0;
}

.field-title {
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.drop-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-xs);
  min-height: 5.5rem;
  padding: var(--spacing-md);
  background: var(--black);
  border: 2px dashed var(--border-primary);
  cursor: pointer;
  text-align: center;
  transition: border-color var(--transition-fast), background-color var(--transition-fast);
}

.drop-zone:hover,
.drop-zone:focus-visible,
.drop-zone--over {
  border-color: var(--blue-primary);
  background: var(--hover-bg);
  outline: none;
}

.file-name {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-white);
}

.file-details {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: var(--spacing-md);
  max-width: 100%;
  font-size: 0.75rem;
}

.file-size {
  flex: none;
}

.file-hash {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drop-hint {
  font-size: 0.85rem;
}

.file-input {
  display: none;
}

.radio-group {
  align-self: flex-start;
  max-width: 100%;
  flex-wrap: wrap;
}

.radio-label {
  text-transform: uppercase;
  letter-spacing: 1px;
  font-size: 0.8rem;
}

.internet-warning {
  margin: 0;
  color: var(--status-medium);
  font-size: 0.75rem;
}

.option-row {
  display: flex;
  gap: var(--spacing-md);
}

.timeout-input {
  flex: 0 0 9rem;
}

.package-input {
  flex: 1 1 auto;
  min-width: 0;
}

.field-error {
  margin: 0;
  color: var(--status-critical);
  font-size: 0.75rem;
}

.error-banner {
  margin: 0;
  padding: var(--spacing-sm) var(--spacing-md);
  border: 2px solid var(--status-critical);
  color: var(--status-critical);
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.form-actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.submit-reason {
  font-size: 0.75rem;
}

.cancel-btn {
  color: var(--text-gray);
}

.submit-btn {
  color: var(--blue-primary);
}
</style>
