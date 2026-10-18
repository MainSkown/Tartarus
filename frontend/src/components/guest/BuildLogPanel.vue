<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import CopyButton from '@/components/CopyButton.vue'
import PaneHeading from '@/components/PaneHeading.vue'
import { t } from '@/i18n'

const props = defineProps<{ lines: readonly string[] }>()

// What the guest itself printed, as opposed to the control service's own progress lines.
const GUEST_PREFIX = 'guest: '
const AT_END_SLACK_PX = 24

const body = ref<HTMLElement>()
const following = ref(true)

const rows = computed(() => props.lines.map((text, index) => ({ text, index, fromGuest: text.startsWith(GUEST_PREFIX) })))

function scrollToEnd(): void {
  if (body.value) body.value.scrollTop = body.value.scrollHeight
}

function followIfWanted(): void {
  if (following.value) scrollToEnd()
}

function toggleFollow(): void {
  following.value = !following.value
  followIfWanted()
}

function followAgainAtTheEnd(): void {
  const element = body.value
  if (!element) return
  following.value = element.scrollHeight - element.scrollTop - element.clientHeight <= AT_END_SLACK_PX
}

onMounted(followIfWanted)
watch(() => props.lines, followIfWanted, { flush: 'post' })
</script>

<template>
  <section
    class="build-log"
    data-build="log"
  >
    <div class="build-log__bar">
      <PaneHeading
        :label="t('guests.buildLog.heading')"
        class="build-log__heading"
      />
      <q-btn
        flat
        dense
        square
        no-caps
        :label="following ? t('guests.buildLog.pauseFollow') : t('guests.buildLog.follow')"
        :aria-pressed="following"
        class="build-log__follow text-mono"
        data-build="follow"
        @click="toggleFollow"
      />
      <CopyButton
        :text="lines.join('\n')"
        :what="t('guests.buildLog.noun')"
        :label="t('guests.buildLog.copy')"
      />
    </div>
    <pre
      ref="body"
      class="build-log__body"
      data-build="log-body"
      @scroll.passive="followAgainAtTheEnd"
    ><span
      v-for="row in rows"
      :key="row.index"
      class="build-log__line"
      :class="{ 'build-log__line--guest': row.fromGuest }"
    >{{ row.text }}
</span><span
      v-if="rows.length === 0"
      class="build-log__empty text-gray"
    >{{ t('guests.buildLog.empty') }}</span></pre>
  </section>
</template>

<style scoped>
.build-log {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.build-log__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-xs) var(--spacing-sm);
  margin-bottom: var(--spacing-xs);
  border-bottom: 2px solid var(--border-primary);
}

/* The bar carries the underline, so the buttons sit on it instead of beside a shorter one. */
.build-log__bar :deep(.pane-heading) {
  flex: 1 1 auto;
  margin: 0;
  border-bottom: none;
}

.build-log__follow {
  color: var(--blue-primary);
  font-size: 0.75rem;
}

.build-log__body {
  flex: 1 1 auto;
  min-height: 6rem;
  max-height: 20rem;
  margin: 0;
  overflow: auto;
  font-size: 0.8rem;
  line-height: 1.45;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  scrollbar-width: thin;
  scrollbar-color: var(--blue-darker) var(--black);
}

.build-log__line--guest {
  color: var(--text-gray);
}
</style>
