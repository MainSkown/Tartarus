<script setup lang="ts">
import { computed } from 'vue'
import type { AnalysisRead } from '@/api'
import DesktopPanel from '@/components/DesktopPanel.vue'
import { useLastScreenshot } from '@/composables/use-last-screenshot'
import { isTerminalStatus } from '@/services/analysis-status'
import { hasDesktop, phaseForRun, type DesktopPhase } from '@/services/desktop-close'
import { analysisDesktopPath } from '@/services/desktop-url'
import { screenshotUrl } from '@/services/screenshot-url'

const props = defineProps<{ analysis: AnalysisRead; endRequested?: boolean }>()

const { last } = useLastScreenshot(
  () => props.analysis.id,
  () => props.analysis.status,
)

const lastScreenshot = computed(() =>
  isTerminalStatus(props.analysis.status) && last.value > 0 ? screenshotUrl(props.analysis.id, last.value) : undefined,
)

function phaseOfRun(phase: DesktopPhase): DesktopPhase {
  return phaseForRun(phase, { status: props.analysis.status, endRequested: props.endRequested === true })
}
</script>

<template>
  <DesktopPanel
    data-live="desktop"
    :path="analysisDesktopPath(analysis.id)"
    :wanted="hasDesktop(analysis.status)"
    :adjust-phase="phaseOfRun"
    :screenshot="lastScreenshot"
  />
</template>
