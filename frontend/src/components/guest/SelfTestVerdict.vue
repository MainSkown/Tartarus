<script setup lang="ts">
import BuildNotice from '@/components/guest/BuildNotice.vue'
import type { Check, SelfTestVerdict } from '@/services/guest-build'

defineProps<{
  passed: boolean
  guest: string
  /** What to say when the self-test left no details of its own. */
  message: string
  verdict?: SelfTestVerdict
}>()

function checkIcon(check: Check): string {
  return check.ok ? 'check_circle' : 'cancel'
}
</script>

<template>
  <BuildNotice
    :tone="passed ? 'green' : 'red'"
    :title="passed ? 'GUEST READY' : 'SELF-TEST FAILED'"
    :icon="passed ? 'check_circle' : 'dangerous'"
    :data-verdict="passed ? 'passed' : 'failed'"
  >
    <p class="verdict__message">
      {{ verdict?.message ?? message }}
    </p>
    <p
      v-if="!passed"
      class="verdict__consequence"
    >
      The guest <strong class="text-mono">{{ guest }}</strong> is failed and unregistered from CAPE, so no analysis
      can be started on it. Delete it on the Guest VM page and build it again.
    </p>

    <template v-if="verdict">
      <section
        v-if="verdict.signals.length > 0"
        class="verdict__section"
      >
        <h3 class="verdict__heading text-mono">
          SIGNALS
        </h3>
        <ul class="verdict__checks">
          <li
            v-for="signal in verdict.signals"
            :key="signal.id"
            class="verdict__check"
            :class="{ 'verdict__check--failing': !signal.ok }"
            data-verdict="signal"
            :data-ok="String(signal.ok)"
          >
            <q-icon
              :name="checkIcon(signal)"
              size="16px"
              aria-hidden="true"
            />
            <span class="verdict__check-label text-mono">{{ signal.label }}</span>
            <span class="verdict__check-text">{{ signal.message }}</span>
          </li>
        </ul>
      </section>

      <section
        v-if="verdict.proofs.length > 0"
        class="verdict__section"
      >
        <h3 class="verdict__heading text-mono">
          PROOFS
        </h3>
        <ul class="verdict__checks">
          <li
            v-for="proof in verdict.proofs"
            :key="proof.id"
            class="verdict__check"
            :class="{ 'verdict__check--failing': !proof.ok }"
            data-verdict="proof"
            :data-ok="String(proof.ok)"
          >
            <q-icon
              :name="checkIcon(proof)"
              size="16px"
              aria-hidden="true"
            />
            <span class="verdict__check-label text-mono">{{ proof.label }}</span>
            <span class="verdict__check-text">{{ proof.message }}</span>
          </li>
        </ul>
      </section>

      <section
        v-if="verdict.giveaways.length > 0"
        class="verdict__section verdict__giveaways"
      >
        <h3 class="verdict__heading text-mono">
          A SAMPLE CAN TELL THIS IS A SANDBOX
        </h3>
        <ul class="verdict__list">
          <li
            v-for="giveaway in verdict.giveaways"
            :key="giveaway"
            class="text-mono"
            data-verdict="giveaway"
          >
            {{ giveaway }}
          </li>
        </ul>
      </section>

      <router-link
        v-if="verdict.analysisId !== undefined"
        :to="`/analyses/${verdict.analysisId}`"
        class="verdict__analysis text-mono"
      >
        self-test analysis #{{ verdict.analysisId }}
      </router-link>
    </template>

    <template #actions>
      <q-btn
        outline
        square
        label="[OPEN GUEST VM]"
        class="verdict__open text-mono"
        to="/guest"
      />
    </template>
  </BuildNotice>
</template>

<style scoped>
.verdict__message,
.verdict__consequence {
  margin: 0;
}

.verdict__consequence {
  margin-top: var(--spacing-sm);
  color: var(--text-gray-light);
}

.verdict__section {
  margin-top: var(--spacing-md);
}

.verdict__heading {
  margin: 0 0 var(--spacing-xs);
  color: var(--blue-primary);
  font-size: 0.65rem;
  /* Quasar's typography gives h3 a tall line-height that shrinking the font doesn't undo. */
  line-height: 1.2;
  letter-spacing: 1px;
}

.verdict__checks,
.verdict__list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.verdict__check {
  display: grid;
  grid-template-columns: 1rem 11rem minmax(0, 1fr);
  align-items: baseline;
  gap: var(--spacing-sm);
  padding: 2px var(--spacing-xs);
  font-size: 0.85rem;
}

.verdict__check .q-icon {
  align-self: center;
  color: var(--status-success);
}

.verdict__check-label {
  color: var(--text-gray-light);
  font-size: 0.75rem;
}

.verdict__check--failing {
  background: rgba(239, 68, 68, 0.12);
  color: var(--status-critical);
}

.verdict__check--failing .q-icon,
.verdict__check--failing .verdict__check-label {
  color: var(--status-critical);
}

.verdict__giveaways {
  padding: var(--spacing-sm);
  border: 1px solid var(--status-medium);
}

.verdict__giveaways .verdict__heading {
  color: var(--status-medium);
}

.verdict__list {
  padding-left: var(--spacing-md);
  list-style: disc;
  font-size: 0.85rem;
  overflow-wrap: anywhere;
}

.verdict__analysis {
  display: inline-block;
  margin-top: var(--spacing-md);
  font-size: 0.85rem;
}

.verdict__open {
  color: var(--blue-primary);
}

@media (max-width: 700px) {
  /* Label and message stack, so the gap inside one check must be smaller than the gap between two. */
  .verdict__check {
    grid-template-columns: 1rem minmax(0, 1fr);
    row-gap: 0;
    padding-block: var(--spacing-xs);
  }

  .verdict__check-text {
    grid-column: 2;
  }
}
</style>
