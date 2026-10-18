<script setup lang="ts">
import { computed, onMounted, ref, shallowRef } from 'vue'
import { useDialogPluginComponent } from 'quasar'
import { useRouter } from 'vue-router'
import { settingsRead } from '@/api'
import type { Route } from '@/api'
import GuestOptionRow from '@/components/GuestOptionRow.vue'
import { useGuestChoice } from '@/composables/use-guest-choice'
import { t } from '@/i18n'
import { sha256Hex } from '@/services/file-hash'
import { formatFileSize } from '@/services/file-size'
import { useGuestBlockReason } from '@/services/guest-gate'
import { BUILT_ROUTES } from '@/services/routes'
import type { ValidationIssue } from '@/services/validation-errors'
import { SubmissionRejected, useAnalysesStore, type SubmitOptions } from '@/stores/analyses'

defineEmits([...useDialogPluginComponent.emits])
const { dialogRef, onDialogHide, onDialogOK, onDialogCancel } = useDialogPluginComponent()

const TIMEOUT_MIN_SECONDS = 60
const TIMEOUT_MAX_SECONDS = 1200
const SECONDS_PER_MINUTE = 60
const FORM_FIELDS = ['file', 'route', 'timeout', 'guest', 'package', 'interactive'] as const
type FormField = (typeof FORM_FIELDS)[number]

function formatMinutes(seconds: number): string {
  return t('submit.timeout.minutes', { minutes: Math.round((seconds / SECONDS_PER_MINUTE) * 10) / 10 })
}

const analyses = useAnalysesStore()
const router = useRouter()
const guestBlockReason = useGuestBlockReason()

const file = shallowRef<File>()
const hash = ref<string>()
const route = ref<Route>('inetsim')
const timeoutText = ref('180')
const defaultGuestSetting = ref<string | null>()
const guestChoice = useGuestChoice(defaultGuestSetting)
const interactive = ref(false)

const dragOver = ref(false)
const dropError = ref<string>()
const submitting = ref(false)
const fieldErrors = ref<Partial<Record<FormField, string>>>({})
const errorBanner = ref<string>()
const fileInput = ref<HTMLInputElement>()

const timeoutError = computed(() => {
  const seconds = Number(timeoutText.value)
  const valid = timeoutText.value.trim() !== '' && Number.isInteger(seconds)
  return valid && seconds >= TIMEOUT_MIN_SECONDS && seconds <= TIMEOUT_MAX_SECONDS
    ? undefined
    : t('submit.timeout.range', { min: TIMEOUT_MIN_SECONDS, max: TIMEOUT_MAX_SECONDS })
})

const interactiveNote = computed(() => {
  if (!interactive.value) return t('submit.interactive.off')
  if (timeoutError.value) return t('submit.interactive.on')
  return t('submit.interactive.onWithLength', { minutes: formatMinutes(Number(timeoutText.value)) })
})

const emptyGuestText = computed(() =>
  guestChoice.noGuestReason.value ? t('submit.guest.none') : t('submit.guest.loading'),
)

const blockReason = computed(
  () =>
    guestChoice.noGuestReason.value ??
    guestBlockReason.value ??
    (file.value ? undefined : t('submit.blocked.chooseSample')),
)
const canSubmit = computed(() => !blockReason.value && !timeoutError.value && !submitting.value)

const submitOptions = computed<SubmitOptions>(() => ({
  route: route.value,
  timeout: Number(timeoutText.value),
  interactive: interactive.value,
  ...guestChoice.optionPayload.value,
}))

async function applySettingsDefaults(): Promise<void> {
  const { data } = await settingsRead()
  if (data?.default_route && BUILT_ROUTES.includes(data.default_route)) route.value = data.default_route
  const defaultTimeout = data?.default_timeout
  if (defaultTimeout && defaultTimeout >= TIMEOUT_MIN_SECONDS && defaultTimeout <= TIMEOUT_MAX_SECONDS) {
    timeoutText.value = String(defaultTimeout)
  }
  interactive.value = data?.default_interactive === true
  defaultGuestSetting.value = data?.default_guest
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
    dropError.value = t('submit.file.dropOneAtATime')
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
    else errorBanner.value = t('submit.error.unreachable')
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  void applySettingsDefaults()
  void guestChoice.load()
})
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
          {{ t('submit.title') }}
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
                >{{ t('submit.file.hash', { hash: hash ?? t('submit.file.hashing') }) }}</span>
              </span>
            </template>
            <span
              v-else
              class="drop-hint text-mono text-gray"
            >{{ t('submit.file.dropHint') }}</span>
          </div>
          <input
            ref="fileInput"
            type="file"
            class="file-input"
            tabindex="-1"
            :aria-label="t('submit.file.label')"
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
          <q-select
            v-if="!guestChoice.listUnavailable.value"
            v-model="guestChoice.guestName.value"
            :options="guestChoice.guestOptions.value"
            option-value="name"
            option-label="name"
            option-disable="disabled"
            outlined
            dense
            hide-bottom-space
            emit-value
            map-options
            :label="t('submit.guest.label')"
            stack-label
            :disable="submitting"
            :error="Boolean(fieldErrors.guest)"
            :error-message="fieldErrors.guest"
            popup-content-class="guest-select-menu"
            class="guest-select text-mono"
          >
            <template #selected>
              <GuestOptionRow
                v-if="guestChoice.chosenOption.value"
                :option="guestChoice.chosenOption.value"
              />
              <span
                v-else
                class="guest-select__empty"
              >{{ emptyGuestText }}</span>
            </template>
            <template #option="{ opt, itemProps }">
              <q-item v-bind="itemProps">
                <q-item-section>
                  <GuestOptionRow :option="opt" />
                </q-item-section>
              </q-item>
            </template>
          </q-select>
          <p
            v-else
            class="guest-unavailable text-gray"
            role="status"
          >
            {{ t('submit.guest.unavailable') }}
          </p>
        </div>

        <div class="form-field">
          <span class="field-title text-mono">{{ t('submit.route.title') }}</span>
          <div
            class="radio-group"
            role="radiogroup"
            :aria-label="t('submit.route.group')"
          >
            <template
              v-for="option in BUILT_ROUTES"
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
            {{ t('submit.route.internetWarning') }}
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
            :label="t('submit.timeout.label')"
            :suffix="t('submit.timeout.unit')"
            :disable="submitting"
            :error="Boolean(timeoutError ?? fieldErrors.timeout)"
            :error-message="timeoutError ?? fieldErrors.timeout"
            class="timeout-input"
          />
          <q-select
            v-model="guestChoice.packageName.value"
            :options="guestChoice.packageOptions.value"
            outlined
            dense
            hide-bottom-space
            :label="t('submit.package.label')"
            :disable="submitting"
            :error="Boolean(fieldErrors.package)"
            :error-message="fieldErrors.package"
            class="package-input text-mono"
          />
        </div>

        <div class="form-field">
          <q-toggle
            v-model="interactive"
            dense
            :label="t('submit.interactive.label')"
            :disable="submitting"
            class="interactive-toggle text-mono"
          />
          <p class="interactive-note text-gray">
            {{ interactiveNote }}
          </p>
          <p
            v-if="fieldErrors.interactive"
            class="field-error interactive-error"
            role="alert"
          >
            {{ fieldErrors.interactive }}
          </p>
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
          >
            {{ blockReason }}
            <router-link
              v-if="guestChoice.noGuestReason.value"
              to="/guest"
              class="guest-link"
            >{{ t('submit.guest.openGuestVm') }}</router-link>
          </span>
          <q-space />
          <q-btn
            flat
            square
            :label="t('common.cancel')"
            class="cancel-btn text-mono"
            :disable="submitting"
            @click="onDialogCancel"
          />
          <q-btn
            outline
            square
            type="submit"
            :label="t('submit.actions.detonate')"
            class="submit-btn text-mono"
            :disable="!canSubmit"
            :loading="submitting"
          />
        </div>
      </form>
    </q-card>
  </q-dialog>
</template>

<!-- Not scoped: the options menu is teleported out of the dialog. -->
<style>
/* The dialog is as wide as the viewport allows (560px, 94vw, or the viewport less Quasar's 24px gutters) with 24px padding and a 2px border; the menu may not outgrow the select it opens from. */
.guest-select-menu {
  max-width: calc(min(560px, 94vw, 100vw - 2 * var(--spacing-lg)) - 2 * var(--spacing-lg) - 4px);
}

.guest-select-menu .guest-option-row {
  width: 100%;
}
</style>

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
  flex: 0 0 12rem;
}

.timeout-input :deep(input[type='number']) {
  appearance: textfield;
}

.timeout-input :deep(input[type='number']::-webkit-inner-spin-button) {
  appearance: none;
}

.package-input {
  flex: 1 1 auto;
  min-width: 0;
}

.interactive-toggle {
  align-self: flex-start;
  font-size: 0.8rem;
  letter-spacing: 1px;
}

.interactive-note {
  margin: 0;
  font-size: 0.75rem;
  /* Both notes fit two lines at the dialog width, so flipping the switch does not move the form. */
  line-height: 1.5;
  min-height: 3em;
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
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-sm);
}

.submit-reason {
  flex: 1 1 14rem;
  min-width: 0;
  font-size: 0.75rem;
  overflow-wrap: anywhere;
}

.guest-link {
  color: var(--blue-primary);
  white-space: nowrap;
}

.guest-unavailable {
  margin: 0;
  font-size: 0.75rem;
}

.guest-select {
  min-width: 0;
}

/* A chip is taller than the plain text of the other fields; without the room it touches the floating label. */
.guest-select :deep(.q-field__control) {
  min-height: 3rem;
}

.guest-select__empty {
  color: var(--text-gray);
  font-size: 0.8rem;
}

.guest-select :deep(.q-field__native) {
  flex-wrap: nowrap;
  padding-top: 0.9rem;
  padding-bottom: 0.3rem;
  overflow: hidden;
}

.cancel-btn {
  color: var(--text-gray);
}

.submit-btn {
  color: var(--blue-primary);
}
</style>
