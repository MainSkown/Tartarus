<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import CopyButton from '@/components/CopyButton.vue'
import PaneHeading from '@/components/PaneHeading.vue'
import { t } from '@/i18n'
import { logRows } from '@/services/build-log'

const props = defineProps<{ lines: readonly string[] }>()

const AT_END_SLACK_PX = 24

const body = ref<HTMLElement>()
const following = ref(true)

const rows = computed(() => logRows(props.lines))

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
    <PaneHeading :label="t('guests.buildLog.heading')">
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
    </PaneHeading>
    <pre
      ref="body"
      class="build-log__body"
      data-build="log-body"
      @scroll.passive="followAgainAtTheEnd"
    ><template
      v-for="row in rows"
      :key="row.index"
    ><span
      v-if="row.kind === 'progress'"
      class="build-log__progress"
      data-build="log-progress"
    ><span class="build-log__progress-label">{{ row.label }}</span><progress
      class="build-log__bar"
      :value="row.percent"
      max="100"
      :aria-label="row.label"
    /></span><span
      v-else
      class="build-log__line"
      :class="{ 'build-log__line--guest': row.fromGuest }"
    >{{ row.text }}
</span></template><span
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

.build-log__follow {
  color: var(--blue-primary);
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

/* A thin bar on its own row: the figure keeps its place in the story, without a bare number to puzzle over. */
.build-log__progress {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  color: var(--text-gray-dark);
  font-size: 0.7rem;
  letter-spacing: 1px;
}

.build-log__progress-label {
  flex: none;
  min-width: 9rem;
}

.build-log__bar {
  flex: 0 1 12rem;
  min-width: 3rem;
  height: 6px;
  border-width: 1px;
  box-shadow: none;
}
</style>
