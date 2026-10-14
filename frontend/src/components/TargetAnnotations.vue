<script setup lang="ts">
import NoteEditor from '@/components/NoteEditor.vue'
import TagInput from '@/components/TagInput.vue'
import ViewState from '@/components/ViewState.vue'
import { useAnnotationsStore, type AnnotationTarget } from '@/stores/annotations'

const SKELETON_LINES = 3

/**
 * The "tags and note" section of an event or a process. When it cannot be edited (an event of a
 * run that is not finished) it shows what exists and `hint` says why there are no controls.
 */
withDefaults(defineProps<{ target: AnnotationTarget; editable?: boolean; hint?: string }>(), { editable: true, hint: undefined })

const annotations = useAnnotationsStore()
</script>

<template>
  <section class="target-annotations">
    <h4 class="target-annotations__heading text-mono">
      TAGS AND NOTE
    </h4>
    <div
      v-if="annotations.loading && annotations.tags.length + annotations.notes.length === 0"
      class="target-annotations__skeleton"
      aria-busy="true"
      aria-label="Loading tags and note"
    >
      <span
        v-for="line in SKELETON_LINES"
        :key="line"
        class="skeleton"
      />
    </div>
    <ViewState
      v-else
      :error="annotations.loadError"
      @retry="annotations.reload"
    >
      <p
        v-if="!editable && hint"
        class="target-annotations__hint text-mono text-gray"
      >
        {{ hint }}
      </p>
      <TagInput
        :target="target"
        :editable="editable"
      />
      <h5 class="target-annotations__label text-mono">
        NOTE
      </h5>
      <NoteEditor
        :target="target"
        :editable="editable"
        label="Note"
      />
    </ViewState>
  </section>
</template>

<style scoped>
.target-annotations__heading {
  margin: 0 0 var(--spacing-xs);
  color: var(--blue-primary);
  font-size: 0.65rem;
  line-height: 1.2;
  letter-spacing: 1px;
}

.target-annotations__label {
  margin: var(--spacing-sm) 0 var(--spacing-xs);
  color: var(--text-gray);
  font-size: 0.6rem;
  line-height: 1.2;
  letter-spacing: 1px;
}

.target-annotations__hint {
  margin: 0 0 var(--spacing-xs);
  font-size: 0.7rem;
}

.target-annotations__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.target-annotations__skeleton .skeleton {
  height: 12px;
}

.target-annotations__skeleton .skeleton:nth-child(2) {
  width: 60%;
}
</style>
