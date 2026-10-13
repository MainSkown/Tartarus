<script setup lang="ts">
import { computed } from 'vue'
import { phaseMessage, retryLabel, type DesktopPhase } from '@/services/desktop-close'

const props = defineProps<{ phase: DesktopPhase; reason?: string; screenshot?: string }>()
const emit = defineEmits<{ retry: [] }>()

const text = computed(() => phaseMessage(props.phase, props.reason))
const detail = computed(() => (props.reason && props.reason !== text.value ? props.reason : undefined))
const busy = computed(() => props.phase === 'connecting' || props.phase === 'waiting')
</script>

<template>
  <div
    class="desktop-message"
    data-desktop="message"
  >
    <img
      v-if="screenshot"
      :src="screenshot"
      alt="The last screenshot of the guest"
      class="desktop-message__shot"
      data-desktop="last-screenshot"
    >
    <div class="desktop-message__body text-mono">
      <span
        v-if="busy"
        class="loader"
        role="status"
        aria-label="Loading"
      />
      <p class="desktop-message__text">
        &gt; {{ text }}
      </p>
      <p
        v-if="detail"
        class="desktop-message__detail text-gray"
      >
        {{ detail }}
      </p>
      <q-btn
        v-if="retryLabel(phase)"
        outline
        square
        dense
        no-caps
        :label="retryLabel(phase)"
        class="desktop-message__retry"
        data-desktop="retry"
        @click="emit('retry')"
      />
    </div>
  </div>
</template>

<style scoped>
.desktop-message {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.desktop-message__shot {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  opacity: 0.35;
}

.desktop-message__body {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-sm);
  box-sizing: border-box;
  max-width: 100%;
  max-height: 100%;
  overflow-y: auto;
  padding: var(--spacing-sm) var(--spacing-md);
  background: rgba(0, 0, 0, 0.75);
  text-align: center;
}

.desktop-message__text,
.desktop-message__detail {
  margin: 0;
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.desktop-message__detail {
  font-size: 0.7rem;
}

.desktop-message__retry {
  color: var(--blue-primary);
}
</style>
