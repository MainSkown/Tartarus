<script setup lang="ts">
import { computed } from 'vue'
import CopyButton from '@/components/CopyButton.vue'
import ViewState from '@/components/ViewState.vue'
import { useEventDetail } from '@/composables/use-event-detail'
import { t } from '@/i18n'
import { disasmLines, hexRows } from '@/services/hexdump'
import { processCommandLine, regionPreview } from '@/services/memory-findings'

const SKELETON_LINES = 4

const props = defineProps<{ analysisId: number; eventId: string }>()

const { detail, error, reload } = useEventDetail(
  () => props.analysisId,
  () => props.eventId,
)

const preview = computed(() => regionPreview(detail.value?.source ?? {}))
const rows = computed(() => (preview.value.hexdump === null ? [] : hexRows(preview.value.hexdump)))
const byteCount = computed(() => rows.value.reduce((count, row) => count + row.bytes.length, 0))
const disassembly = computed(() => (preview.value.disasm === null ? [] : disasmLines(preview.value.disasm)))
const commandLine = computed(() => processCommandLine(detail.value?.source ?? {}))
</script>

<template>
  <div class="finding-detail">
    <ViewState
      v-if="error"
      :error="error"
      @retry="reload"
    />
    <div
      v-else-if="!detail"
      class="finding-detail__skeleton"
      aria-busy="true"
      :aria-label="t('artifacts.memory.detail.loading')"
    >
      <span
        v-for="line in SKELETON_LINES"
        :key="line"
        class="skeleton"
      />
    </div>
    <template v-else>
      <div
        v-if="rows.length"
        class="finding-detail__preview"
      >
        <section class="finding-detail__section">
          <div class="finding-detail__bar">
            <h4 class="finding-detail__heading text-mono">
              {{ t('artifacts.memory.detail.hexdump', { count: byteCount }) }}
            </h4>
            <CopyButton
              :text="preview.hexdump ?? ''"
              :what="t('artifacts.memory.detail.hexdumpNoun')"
            />
          </div>
          <div class="finding-detail__code code-block text-mono">
            <div
              v-for="row in rows"
              :key="row.offset"
              class="hex-row"
            >
              <span class="hex-row__offset text-gray">{{ row.offset }}</span>
              <span class="hex-row__bytes">{{ row.bytes.join(' ') }}</span>
              <span class="hex-row__text text-gray">{{ row.text }}</span>
            </div>
          </div>
        </section>
        <section
          v-if="disassembly.length"
          class="finding-detail__section"
        >
          <div class="finding-detail__bar">
            <h4 class="finding-detail__heading text-mono">
              {{ t('artifacts.memory.detail.disasm') }}
            </h4>
            <CopyButton
              :text="disassembly.join('\n')"
              :what="t('artifacts.memory.detail.disasmNoun')"
            />
          </div>
          <pre class="finding-detail__code finding-detail__disasm">{{ disassembly.join('\n') }}</pre>
        </section>
      </div>
      <p
        v-else
        class="finding-detail__none text-mono text-gray"
      >
        {{ t('artifacts.memory.detail.noPreview') }}
      </p>
      <section
        v-if="commandLine"
        class="finding-detail__section"
      >
        <h4 class="finding-detail__heading text-mono">
          {{ t('artifacts.memory.detail.commandLine') }}
        </h4>
        <p class="finding-detail__command-line text-mono">
          {{ commandLine }}
        </p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.finding-detail {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  min-width: 0;
  padding: var(--spacing-sm) 0 var(--spacing-xs);
  white-space: normal;
}

.finding-detail__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.finding-detail__skeleton .skeleton {
  height: 12px;
}

.finding-detail__skeleton .skeleton:nth-child(2) {
  width: 80%;
}

.finding-detail__skeleton .skeleton:nth-child(3) {
  width: 55%;
}

.finding-detail__preview {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 30rem), 1fr));
  gap: var(--spacing-md);
}

.finding-detail__section {
  min-width: 0;
}

.finding-detail__bar {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  margin-bottom: var(--spacing-xs);
}

.finding-detail__heading {
  margin: 0;
  color: var(--blue-primary);
  font-size: 0.65rem;
  line-height: 1.2;
  letter-spacing: 1px;
}

.finding-detail__code {
  margin: 0;
  max-height: 16rem;
  overflow: auto;
  font-size: 0.75rem;
  line-height: 1.5;
}

.finding-detail__disasm {
  white-space: pre;
}

.hex-row {
  display: flex;
  gap: var(--spacing-md);
  white-space: pre;
}

.hex-row__offset {
  flex: none;
}

.hex-row__bytes {
  flex: none;
}

.hex-row__text {
  flex: none;
}

/* The characters column is what a narrow detail can do without: the bytes are the point and still fit. */
@container finding-list (max-width: 900px) {
  .hex-row__text {
    display: none;
  }
}

.finding-detail__none {
  margin: 0;
  font-size: 0.75rem;
}

.finding-detail__command-line {
  margin: 0;
  font-size: 0.75rem;
  overflow-wrap: anywhere;
}
</style>
