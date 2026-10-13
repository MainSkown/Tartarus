<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { screenshotUrl } from '@/services/screenshot-url'

const props = defineProps<{ analysisId: number; count: number; modelValue: number | null }>()
const emit = defineEmits<{ 'update:modelValue': [n: number | null] }>()

// The dialog fades out after the model clears; keeping the last screenshot stops it going blank mid-fade.
const shown = ref(props.modelValue)
watch(
  () => props.modelValue,
  (n) => {
    if (n !== null) shown.value = n
  },
)

const hasPrevious = computed(() => props.modelValue !== null && props.modelValue > 1)
const hasNext = computed(() => props.modelValue !== null && props.modelValue < props.count)

function step(offset: number): void {
  if (props.modelValue === null) return
  const target = props.modelValue + offset
  if (target >= 1 && target <= props.count) emit('update:modelValue', target)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'ArrowLeft') step(-1)
  else if (event.key === 'ArrowRight') step(1)
}

watch(
  () => props.modelValue !== null,
  (open) => {
    if (open) window.addEventListener('keydown', onKeydown)
    else window.removeEventListener('keydown', onKeydown)
  },
  { immediate: true },
)
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <q-dialog
    :model-value="modelValue !== null"
    @update:model-value="emit('update:modelValue', null)"
  >
    <div
      v-if="shown !== null"
      class="screenshot-lightbox"
    >
      <img
        class="screenshot-lightbox__image"
        :src="screenshotUrl(analysisId, shown)"
        :alt="`Screenshot ${shown} of ${count}`"
      >
      <div class="screenshot-lightbox__bar">
        <q-btn
          flat
          square
          dense
          icon="chevron_left"
          aria-label="Previous screenshot"
          :disable="!hasPrevious"
          @click="step(-1)"
        />
        <span class="screenshot-lightbox__position text-mono">{{ shown }} / {{ count }}</span>
        <q-btn
          flat
          square
          dense
          icon="chevron_right"
          aria-label="Next screenshot"
          :disable="!hasNext"
          @click="step(1)"
        />
        <q-space />
        <q-btn
          flat
          square
          dense
          icon="close"
          aria-label="Close"
          @click="emit('update:modelValue', null)"
        />
      </div>
    </div>
  </q-dialog>
</template>

<style scoped>
.screenshot-lightbox {
  display: flex;
  flex-direction: column;
  max-width: 96vw;
  background: var(--card-bg);
  border: 2px solid var(--blue-primary);
}

.screenshot-lightbox__image {
  display: block;
  max-width: 100%;
  max-height: calc(100vh - 8rem);
  object-fit: contain;
  background: var(--black);
}

.screenshot-lightbox__bar {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm);
}

.screenshot-lightbox__position {
  min-width: 6ch;
  text-align: center;
}
</style>
