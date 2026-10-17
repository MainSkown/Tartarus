<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import DesktopPanel from '@/components/DesktopPanel.vue'
import BuildHeader from '@/components/guest/BuildHeader.vue'
import BuildLogPanel from '@/components/guest/BuildLogPanel.vue'
import BuildNotice from '@/components/guest/BuildNotice.vue'
import BuildStepList from '@/components/guest/BuildStepList.vue'
import SelfTestVerdict from '@/components/guest/SelfTestVerdict.vue'
import PaneHeading from '@/components/PaneHeading.vue'
import ViewState from '@/components/ViewState.vue'
import { useGuestBuild } from '@/composables/use-guest-build'
import { failedStep, humanStepName, stepsWithSelfTest } from '@/services/guest-build'
import { guestDesktopPath } from '@/services/desktop-url'

const route = useRoute()
const state = useGuestBuild(() => String(route.params.buildId))

const build = computed(() => state.build.value)
const phase = computed(() => state.phase.value)
const steps = computed(() => stepsWithSelfTest(build.value?.steps ?? [], phase.value))
const failing = computed(() => (build.value ? failedStep(build.value) : undefined))
const verdictShown = computed(() => phase.value === 'ready' || phase.value === 'selftest-failed')
const busy = computed(() => state.busy.value !== undefined)
</script>

<template>
  <div class="build-page">
    <ViewState :loading="phase === 'loading'">
      <template v-if="build">
        <BuildHeader
          :guest="build.guest"
          :kind="build.kind"
          :phase="phase"
          :percent="state.progress.value.percent"
          :message="state.progress.value.message"
          :back-link="!verdictShown"
        />

        <p
          v-if="state.connectionLost.value"
          class="build-page__note text-mono"
          data-build="connection-note"
        >
          &gt; the guest control service is not reachable; trying again
        </p>

        <BuildNotice
          v-if="phase === 'paused'"
          tone="amber"
          title="WAITING FOR YOU"
          icon="pause_circle"
          :error="state.actionError.value"
        >
          <p class="build-page__instructions">
            {{ build.pause?.instructions }}
          </p>
          <p class="build-page__hint text-gray">
            Do it on the guest's desktop below, then continue the build.
          </p>
          <template #actions>
            <q-btn
              outline
              square
              :label="state.busy.value === 'continue' ? '[CONTINUING...]' : '[CONTINUE]'"
              class="build-page__action text-mono"
              :disable="busy"
              @click="state.continueBuild"
            />
          </template>
        </BuildNotice>

        <BuildNotice
          v-else-if="phase === 'failed'"
          tone="red"
          :title="failing ? `${humanStepName(failing.name)} FAILED` : 'BUILD FAILED'"
          icon="dangerous"
          :error="state.actionError.value"
        >
          <p class="build-page__failure text-mono">
            {{ build.message || 'The step failed without a message; the log below may say why.' }}
          </p>
          <p class="build-page__hint text-gray">
            RESUME runs the failed step again. RESTART begins from the first step and discards what has been done.
          </p>
          <template #actions>
            <q-btn
              outline
              square
              :label="state.busy.value === 'resume' ? '[RESUMING...]' : '[RESUME]'"
              class="build-page__action text-mono"
              :disable="busy"
              @click="state.resume"
            />
            <q-btn
              outline
              square
              :label="state.busy.value === 'restart' ? '[RESTARTING...]' : '[RESTART]'"
              class="build-page__restart text-mono"
              :disable="busy"
              @click="state.restart"
            />
          </template>
        </BuildNotice>

        <SelfTestVerdict
          v-else-if="verdictShown"
          :passed="phase === 'ready'"
          :guest="build.guest"
          :message="phase === 'ready' ? 'The guest was built and is ready.' : state.failureMessage.value"
          :verdict="state.verdict.value"
        />

        <div class="build-page__grid">
          <section class="build-page__steps">
            <PaneHeading label="STEPS" />
            <BuildStepList :steps="steps" />
          </section>
          <div class="build-page__main">
            <div
              v-if="state.hasDesktop.value"
              class="build-page__desktop"
            >
              <DesktopPanel
                :path="guestDesktopPath(build.guest)"
                :wanted="true"
                subject="build"
              />
            </div>
            <BuildLogPanel :lines="build.log" />
          </div>
        </div>
      </template>

      <section
        v-else
        class="build-page__missing text-mono"
      >
        <h1 class="build-page__title">
          BUILD
        </h1>
        <p
          v-if="phase === 'not-found'"
          class="text-gray"
        >
          &gt; build not found
        </p>
        <template v-else>
          <p class="text-gray">
            &gt; the guest control service is not reachable
          </p>
          <p class="build-page__hint text-gray">
            trying again every few seconds
          </p>
        </template>
        <q-btn
          outline
          square
          label="[BACK TO GUEST VM]"
          class="build-page__action text-mono"
          to="/guest"
        />
      </section>
    </ViewState>
  </div>
</template>

<style scoped>
.build-page {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  padding: var(--spacing-lg);
}

.build-page__note {
  margin: 0;
  color: var(--status-medium);
  font-size: 0.85rem;
}

.build-page__instructions,
.build-page__failure {
  margin: 0;
  white-space: pre-line;
}

.build-page__failure {
  color: var(--text-white);
  font-size: 0.85rem;
}

.build-page__hint {
  margin: var(--spacing-xs) 0 0;
  font-size: 0.85rem;
}

.build-page__action {
  color: var(--blue-primary);
}

.build-page__restart {
  color: var(--status-critical);
}

.build-page__grid {
  display: grid;
  grid-template-columns: minmax(16rem, 22rem) minmax(0, 1fr);
  gap: var(--spacing-md);
  align-items: start;
}

.build-page__steps,
.build-page__main {
  min-width: 0;
}

.build-page__main {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.build-page__desktop {
  height: clamp(18rem, 55vh, 34rem);
}

.build-page__desktop :deep(.live-desktop) {
  height: 100%;
}

.build-page__missing {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--spacing-sm);
}

.build-page__missing p {
  margin: 0;
}

.build-page__title {
  margin: 0;
  color: var(--blue-primary);
  font-size: 0.9rem;
  line-height: 1.2;
  letter-spacing: 2px;
}

@media (max-width: 900px) {
  .build-page {
    padding: var(--spacing-md);
  }

  .build-page__grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .build-page__desktop {
    height: auto;
  }
}
</style>
