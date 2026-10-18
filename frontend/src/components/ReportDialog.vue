<script setup lang="ts">
import { useDialogPluginComponent } from 'quasar'
import type { ReportVariant } from '@/api'
import { useReportDialog } from '@/composables/use-report-dialog'
import { t } from '@/i18n'
import { REPORT_FORMATS, REPORT_OPTIONS } from '@/services/report-request'

const props = defineProps<{ analysisId: number; filename: string; initialFormat: ReportVariant }>()

defineEmits([...useDialogPluginComponent.emits])
const { dialogRef, onDialogHide, onDialogCancel } = useDialogPluginComponent()

const report = useReportDialog(props.analysisId, props.initialFormat)
</script>

<template>
  <q-dialog
    ref="dialogRef"
    :persistent="report.submitting.value"
    @hide="onDialogHide"
  >
    <q-card class="report-dialog">
      <div class="report-dialog__body">
        <h2 class="report-dialog__title text-mono">
          <span>{{ t('reports.dialog.title') }}</span>
          <span class="report-dialog__id">{{ t('reports.dialog.id', { id: analysisId }) }}</span>
          <span
            class="report-dialog__filename"
            :title="filename"
          >{{ filename }}</span>
        </h2>

        <form
          v-if="report.view.value === 'form'"
          class="report-dialog__form"
          @submit.prevent="report.generate"
        >
          <div class="report-dialog__field">
            <span class="report-dialog__field-title text-mono">{{ t('reports.dialog.format') }}</span>
            <div
              class="radio-group"
              role="radiogroup"
              :aria-label="t('reports.dialog.formatGroup')"
            >
              <template
                v-for="option in REPORT_FORMATS"
                :key="option.value"
              >
                <input
                  :id="`report-format-${option.value}`"
                  v-model="report.format.value"
                  type="radio"
                  name="format"
                  class="radio-input"
                  :value="option.value"
                  :disabled="report.submitting.value"
                >
                <label
                  :for="`report-format-${option.value}`"
                  class="radio-label text-mono"
                >{{ option.label }}</label>
              </template>
            </div>
          </div>

          <div class="report-dialog__field">
            <span class="report-dialog__field-title text-mono">{{ t('reports.dialog.include') }}</span>
            <label
              v-for="option in REPORT_OPTIONS"
              :key="option.key"
              class="report-dialog__option"
            >
              <input
                v-model="report.include[option.key]"
                type="checkbox"
                class="checkbox-input"
                :name="option.key"
                :disabled="report.submitting.value"
              >
              <span class="report-dialog__option-label text-mono">{{ t(option.labelKey) }}</span>
              <span class="report-dialog__option-hint text-gray">{{ t(option.hintKey) }}</span>
            </label>
          </div>

          <p
            v-if="report.refusal.value"
            class="report-dialog__error text-mono"
            role="alert"
          >
            {{ report.refusal.value }}
          </p>

          <div class="report-dialog__actions">
            <q-space />
            <q-btn
              flat
              square
              :label="t('common.cancel')"
              class="report-dialog__cancel text-mono"
              :disable="report.submitting.value"
              @click="onDialogCancel"
            />
            <q-btn
              outline
              square
              type="submit"
              :label="t('reports.dialog.generate')"
              class="report-dialog__primary text-mono"
              :disable="report.submitting.value"
              :loading="report.submitting.value"
            />
          </div>
        </form>

        <div
          v-else-if="report.view.value === 'progress' && report.job.value"
          class="report-dialog__form"
        >
          <div class="report-dialog__progress">
            <progress
              max="100"
              :value="report.job.value.progress"
              :aria-label="t('reports.dialog.progress')"
            />
            <div class="report-dialog__progress-line text-mono">
              <span class="report-dialog__step">{{ report.job.value.step }}</span>
              <span class="report-dialog__percent">{{ t('reports.dialog.percent', { percent: report.job.value.progress }) }}</span>
            </div>
          </div>
          <p class="report-dialog__note text-gray">
            {{ t('reports.dialog.progressNote') }}
          </p>
          <div class="report-dialog__actions">
            <q-space />
            <q-btn
              flat
              square
              :label="t('common.close')"
              class="report-dialog__cancel text-mono"
              @click="onDialogCancel"
            />
          </div>
        </div>

        <div
          v-else-if="report.view.value === 'done'"
          class="report-dialog__form"
        >
          <p class="report-dialog__ready text-mono">
            {{ t('reports.dialog.ready') }}
          </p>
          <p
            class="report-dialog__file text-mono text-gray"
            :title="report.filename.value"
          >
            {{ report.filename.value }}
          </p>
          <div class="report-dialog__actions">
            <q-btn
              flat
              square
              :label="t('reports.dialog.newReport')"
              class="report-dialog__cancel text-mono"
              @click="report.startNewReport"
            />
            <q-space />
            <q-btn
              flat
              square
              :label="t('common.close')"
              class="report-dialog__cancel text-mono"
              @click="onDialogCancel"
            />
            <q-btn
              outline
              square
              :label="t('reports.dialog.download', { format: report.builtFormat.value.toUpperCase() })"
              class="report-dialog__primary text-mono"
              :loading="report.downloading.value"
              @click="report.download"
            />
          </div>
        </div>

        <div
          v-else
          class="report-dialog__form"
        >
          <p
            class="report-dialog__error text-mono"
            role="alert"
          >
            {{ report.failureReason.value }}
          </p>
          <p
            v-if="report.refusal.value"
            class="report-dialog__error text-mono"
            role="alert"
          >
            {{ report.refusal.value }}
          </p>
          <div class="report-dialog__actions">
            <q-btn
              flat
              square
              :label="t('reports.dialog.newReport')"
              class="report-dialog__cancel text-mono"
              @click="report.startNewReport"
            />
            <q-space />
            <q-btn
              flat
              square
              :label="t('common.close')"
              class="report-dialog__cancel text-mono"
              @click="onDialogCancel"
            />
            <q-btn
              outline
              square
              :label="t('common.retry')"
              class="report-dialog__primary text-mono"
              :disable="report.submitting.value"
              :loading="report.submitting.value"
              @click="report.retry"
            />
          </div>
        </div>
      </div>
    </q-card>
  </q-dialog>
</template>

<style scoped>
.report-dialog {
  width: 520px;
  max-width: 94vw;
}

.report-dialog__body {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
  padding: var(--spacing-lg);
}

.report-dialog__title {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-sm);
  margin: 0;
  color: var(--blue-primary);
  font-size: 0.9rem;
  line-height: 1.2;
  letter-spacing: 2px;
}

.report-dialog__id {
  flex: none;
  color: var(--text-gray);
}

.report-dialog__filename {
  min-width: 0;
  overflow: hidden;
  color: var(--text-white);
  letter-spacing: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-dialog__form {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
  min-width: 0;
}

.report-dialog__field {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  min-width: 0;
}

.report-dialog__field-title {
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.radio-group {
  align-self: flex-start;
}

.radio-label {
  text-transform: uppercase;
  letter-spacing: 1px;
  font-size: 0.8rem;
}

.report-dialog__option {
  display: grid;
  grid-template-columns: auto 1fr;
  column-gap: var(--spacing-sm);
  align-items: center;
  cursor: pointer;
}

.report-dialog__option-label {
  font-size: 0.8rem;
  letter-spacing: 1px;
}

.report-dialog__option-hint {
  grid-column: 2;
  font-size: 0.75rem;
  line-height: 1.4;
}

.report-dialog__progress {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.report-dialog__progress-line {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-md);
  font-size: 0.8rem;
}

.report-dialog__step {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-dialog__percent {
  flex: none;
  color: var(--blue-primary);
}

.report-dialog__note {
  margin: 0;
  font-size: 0.75rem;
  line-height: 1.5;
}

.report-dialog__ready {
  margin: 0;
  color: var(--status-success);
}

.report-dialog__file {
  margin: 0;
  overflow-wrap: anywhere;
  font-size: 0.8rem;
}

.report-dialog__error {
  margin: 0;
  padding: var(--spacing-sm) var(--spacing-md);
  border: 2px solid var(--status-critical);
  color: var(--status-critical);
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.report-dialog__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-sm);
}

.report-dialog__actions :deep(.q-btn__content) {
  flex-wrap: nowrap;
  white-space: nowrap;
}

.report-dialog__cancel {
  color: var(--text-gray);
}

.report-dialog__primary {
  color: var(--blue-primary);
}
</style>
