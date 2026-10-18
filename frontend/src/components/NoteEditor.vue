<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Notify } from 'quasar'
import { t } from '@/i18n'
import { formatCount } from '@/services/format-number'
import { MAX_NOTE_LENGTH, NOTE_COUNTER_FROM } from '@/services/note-body'
import { useAnnotationsStore, type AnnotationTarget } from '@/stores/annotations'

type SaveState = 'idle' | 'saving' | 'saved' | 'failed'

const STATUS_LABELS: Record<SaveState, string> = { idle: '', saving: 'SAVING…', saved: 'SAVED', failed: 'NOT SAVED' }

/**
 * The note of one target, edited in place and saved when the field loses focus; an emptied field
 * deletes the note. A failed save keeps the draft and tries again on the next blur. When it is
 * not editable the note is shown as plain text.
 */
const props = withDefaults(defineProps<{ target: AnnotationTarget; editable?: boolean; label: string }>(), {
  editable: true,
})

const annotations = useAnnotationsStore()

const savedBody = computed(() => annotations.noteOf(props.target)?.body ?? '')
const draft = ref(savedBody.value)
const state = ref<SaveState>('idle')

// A note that changes underneath an untouched field (a reload) replaces it; one being typed in is left alone.
watch(savedBody, (next, previous) => {
  if (draft.value === previous) draft.value = next
})

const showCounter = computed(() => draft.value.length >= NOTE_COUNTER_FROM)
const counter = computed(() => t('notes.editor.counter', { current: formatCount(draft.value.length), max: formatCount(MAX_NOTE_LENGTH) }))

async function save(): Promise<void> {
  if (draft.value === savedBody.value) return
  const clearing = draft.value.trim() === ''
  if (clearing && savedBody.value === '') {
    draft.value = ''
    return
  }
  state.value = 'saving'
  if (await annotations.saveNote(props.target, draft.value)) {
    state.value = 'saved'
    if (clearing) draft.value = ''
    Notify.create({ type: 'tt-success', message: clearing ? 'Note removed' : 'Note saved' })
  } else {
    // The API error interceptor has already toasted the reason.
    state.value = 'failed'
  }
}

function onInput(): void {
  state.value = 'idle'
}
</script>

<template>
  <div
    class="note-editor"
    :class="{ 'has-error': state === 'failed' }"
  >
    <template v-if="editable">
      <q-input
        v-model="draft"
        type="textarea"
        autogrow
        outlined
        dense
        square
        dark
        hide-bottom-space
        class="note-editor__field"
        :error="state === 'failed'"
        :maxlength="MAX_NOTE_LENGTH"
        :aria-label="label"
        placeholder="plain text, saved when you leave the field"
        @update:model-value="onInput"
        @blur="save"
      />
      <div class="note-editor__footer text-mono">
        <span
          v-if="state !== 'idle'"
          class="note-editor__status"
          :class="`note-editor__status--${state}`"
          role="status"
        >{{ STATUS_LABELS[state] }}</span>
        <span
          v-if="showCounter"
          class="note-editor__counter"
          :class="{ 'is-full': draft.length >= MAX_NOTE_LENGTH }"
        >{{ counter }}</span>
      </div>
    </template>
    <template v-else>
      <p
        v-if="savedBody"
        class="note-editor__text"
      >
        {{ savedBody }}
      </p>
      <p
        v-else
        class="note-editor__none text-mono text-gray"
      >
        no note
      </p>
    </template>
  </div>
</template>

<style scoped>
.note-editor {
  min-width: 0;
}

.note-editor__field :deep(textarea) {
  max-height: 24rem;
  font-size: 0.85rem;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.note-editor__field :deep(textarea::placeholder) {
  color: var(--text-gray-dark);
  opacity: 0.8;
}

.note-editor__footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-md);
  min-height: 1.2em;
  margin-top: var(--spacing-xs);
  font-size: 0.65rem;
  letter-spacing: 1px;
}

.note-editor__footer:empty {
  display: none;
}

.note-editor__status--saved {
  color: var(--status-success);
}

.note-editor__status--saving {
  color: var(--text-gray);
}

.note-editor__status--failed,
.note-editor__counter.is-full {
  color: var(--status-critical);
}

.note-editor__counter {
  color: var(--text-gray);
}

.note-editor__text {
  margin: 0;
  font-size: 0.85rem;
  line-height: 1.4;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.note-editor__none {
  margin: 0;
  font-size: 0.75rem;
}
</style>
