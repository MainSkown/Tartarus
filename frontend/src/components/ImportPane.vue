<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import type { AnalysisCreated } from '@/api'
import {
  ImportUploadError,
  readImportHead,
  sizeClassOf,
  sniffImportKind,
  useImportUpload,
  type ImportKind,
  type ImportFailure,
} from '@/composables/use-import-upload'
import { t } from '@/i18n'
import { formatFileSize } from '@/services/file-size'
import { IMPORT_LIMIT_BYTES } from '@/services/import-limits'

const emit = defineEmits<{
  imported: [analysis: AnalysisCreated]
  busy: [busy: boolean]
}>()

const { progress, uploading, upload } = useImportUpload()

const file = shallowRef<File>()
const kind = ref<ImportKind>()
const dragOver = ref(false)
const dropError = ref<string>()
const uploadError = ref<string>()
const fileInput = ref<HTMLInputElement>()

const sizeClass = computed(() => (kind.value ? sizeClassOf(kind.value) : undefined))
const limitBytes = computed(() => (sizeClass.value ? IMPORT_LIMIT_BYTES[sizeClass.value] : undefined))

const kindLabel = computed(() => {
  if (kind.value === 'memory_image') return t('submit.import.kind.memoryImage')
  if (kind.value === 'pcap' || kind.value === 'pcapng') return t('submit.import.kind.capture')
  return undefined
})

const inputError = computed(() => {
  if (!file.value || !kind.value) return undefined
  if (kind.value === 'unsupported') return t('submit.import.kind.unsupported')
  if (limitBytes.value !== undefined && file.value.size > limitBytes.value) {
    return t('submit.import.tooLarge', { limit: formatFileSize(limitBytes.value) })
  }
  return undefined
})

const shownError = computed(() => uploadError.value ?? dropError.value ?? inputError.value)
const canImport = computed(() => Boolean(file.value && sizeClass.value && !inputError.value && !uploading.value))
const percent = computed(() => Math.round(progress.value * 100))

watch(uploading, (busy) => emit('busy', busy))

async function chooseFile(chosen: File): Promise<void> {
  file.value = chosen
  kind.value = undefined
  dropError.value = undefined
  uploadError.value = undefined
  const detected = sniffImportKind(await readImportHead(chosen))
  // A slower sniff of an earlier choice must not label the file chosen since.
  if (file.value === chosen) kind.value = detected
}

function onFileInput(event: Event): void {
  const chosen = (event.target as HTMLInputElement).files?.[0]
  if (chosen) void chooseFile(chosen)
}

function onDrop(event: DragEvent): void {
  dragOver.value = false
  const dropped = event.dataTransfer?.files
  if (!dropped?.length || uploading.value) return
  if (dropped.length > 1) {
    dropError.value = t('submit.import.file.dropOneAtATime')
    return
  }
  void chooseFile(dropped[0]!)
}

function failureMessage(error: unknown): string {
  if (!(error instanceof ImportUploadError)) return t('submit.error.unreachable')
  const messages: Partial<Record<ImportFailure, string>> = {
    too_large: t('submit.import.error.tooLarge'),
    unsupported: t('submit.import.error.unsupported'),
    network: t('submit.error.unreachable'),
  }
  return messages[error.failure] ?? error.message
}

async function importFile(): Promise<void> {
  if (!canImport.value || !file.value || !kind.value) return
  uploadError.value = undefined
  try {
    emit('imported', await upload(file.value, kind.value))
  } catch (error) {
    uploadError.value = failureMessage(error)
  }
}
</script>

<template>
  <div class="import-pane">
    <h2 class="pane-title text-mono">
      {{ t('submit.import.title') }}
    </h2>

    <div class="form-field">
      <div
        class="drop-zone"
        :class="{ 'drop-zone--over': dragOver }"
        role="button"
        :tabindex="uploading ? -1 : 0"
        @click="!uploading && fileInput?.click()"
        @keydown.enter.prevent="!uploading && fileInput?.click()"
        @keydown.space.prevent="!uploading && fileInput?.click()"
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
              v-if="kindLabel"
              class="import-kind"
            >{{ kindLabel }}</span>
          </span>
        </template>
        <span
          v-else
          class="drop-hint text-mono text-gray"
        >{{ t('submit.import.file.dropHint') }}</span>
      </div>
      <input
        ref="fileInput"
        type="file"
        class="import-file-input"
        tabindex="-1"
        :disabled="uploading"
        :aria-label="t('submit.import.file.label')"
        @change="onFileInput"
      >
      <p
        v-if="shownError"
        class="field-error import-error"
        role="alert"
      >
        {{ shownError }}
      </p>
      <p
        v-if="kind === 'memory_image'"
        class="import-memory-note text-gray"
      >
        {{ t('submit.import.memoryNote') }}
      </p>
      <p class="import-limits text-gray">
        {{
          t('submit.import.limits', {
            capture: formatFileSize(IMPORT_LIMIT_BYTES.capture),
            memoryImage: formatFileSize(IMPORT_LIMIT_BYTES.memory_image),
          })
        }}
      </p>
    </div>

    <div
      v-if="uploading"
      class="import-progress-group"
    >
      <q-linear-progress
        :value="progress"
        color="blue-primary"
        track-color="grey-9"
        size="4px"
        class="import-progress-bar"
      />
      <p class="import-progress text-mono text-gray">
        {{ t('submit.import.uploading', { percent }) }}
      </p>
    </div>

    <div class="form-actions">
      <span
        v-if="!file"
        class="import-reason text-mono text-gray"
      >{{ t('submit.import.blocked.choose') }}</span>
      <q-space />
      <q-btn
        outline
        square
        type="button"
        :label="t('submit.import.actions.import')"
        class="import-btn text-mono"
        :disable="!canImport"
        :loading="uploading"
        @click="importFile"
      />
    </div>
  </div>
</template>

<style scoped>
.import-pane {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
  padding: var(--spacing-lg);
}

.pane-title {
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
  min-width: 0;
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

.drop-hint {
  font-size: 0.85rem;
}

.import-file-input {
  display: none;
}

.import-memory-note,
.import-limits {
  margin: 0;
  font-size: 0.75rem;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.field-error {
  margin: 0;
  color: var(--status-critical);
  font-size: 0.75rem;
  overflow-wrap: anywhere;
}

.import-progress-group {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.import-progress {
  margin: 0;
  font-size: 0.75rem;
}

.form-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-sm);
}

.import-reason {
  flex: 1 1 14rem;
  min-width: 0;
  font-size: 0.75rem;
  overflow-wrap: anywhere;
}

.import-btn {
  color: var(--blue-primary);
}
</style>
