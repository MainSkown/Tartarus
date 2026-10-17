<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import GuestBadges from '@/components/guest/GuestBadges.vue'
import GuestIdentityField from '@/components/guest/GuestIdentityField.vue'
import GuestNameField from '@/components/guest/GuestNameField.vue'
import GuestNotice from '@/components/guest/GuestNotice.vue'
import GuestResourcesFields from '@/components/guest/GuestResourcesFields.vue'
import ProfileOptionField from '@/components/guest/ProfileOptionField.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import ViewState from '@/components/ViewState.vue'
import { useGuestClone } from '@/composables/use-guest-clone'
import { blockingWarning, cloneSummary, sourceNotReadyMessage } from '@/services/guest-wizard-view'

const route = useRoute()
const sourceName = computed(() => String(route.params.name))
const clone = useGuestClone(sourceName.value)
void clone.load()

const USERNAME_REASON = 'A different username needs a build: renaming leaves the old profile folder behind.'
const LOCKED_REASON = 'Fixed on a clone; a build can change it.'
</script>

<template>
  <div class="clone-page">
    <div class="clone-header">
      <h1 class="section-title text-mono">
        CLONE <span class="clone-header__source">{{ sourceName }}</span>
      </h1>
      <template v-if="clone.source.value">
        <StatusBadge :guest-state="clone.source.value.state" />
        <GuestBadges :badges="clone.source.value.badges ?? []" />
      </template>
      <q-btn
        flat
        square
        label="[CANCEL]"
        class="clone-cancel text-mono"
        to="/guest"
      />
    </div>

    <ViewState
      :loading="clone.status.value === 'loading'"
      :error="clone.status.value === 'failed' ? clone.loadError.value : undefined"
      @retry="clone.load"
    >
      <div
        v-if="clone.status.value === 'unknown' || clone.status.value === 'not-ready'"
        class="clone-unavailable"
      >
        <GuestNotice tone="error">
          <template v-if="clone.source.value">
            {{ sourceNotReadyMessage(clone.source.value.name, clone.source.value.state) }}
          </template>
          <template v-else>
            There is no guest called {{ sourceName }}.
          </template>
        </GuestNotice>
        <router-link
          to="/guest"
          class="clone-back text-mono"
        >
          [BACK TO GUEST VM]
        </router-link>
      </div>

      <form
        v-else
        class="clone-form"
        @submit.prevent="clone.submit"
      >
        <p class="clone-summary">
          {{ cloneSummary(sourceName) }}
        </p>

        <section class="clone-section">
          <h2 class="clone-section__title text-mono">
            NEW GUEST
          </h2>
          <GuestNameField
            v-model="clone.name.value"
            label="NEW NAME"
            :error="clone.errors.value.name"
          />
          <GuestIdentityField
            v-if="clone.machineEditable.value && clone.profile.value"
            v-model="clone.machine.value"
            :label="clone.profile.value.identity.machine.label.toUpperCase()"
            :error="clone.errors.value['identity.machine']"
            placeholder="chosen at clone time"
            hint="A realistic one is chosen when this is left blank; it is never the source's."
          />
          <GuestIdentityField
            v-if="clone.source.value?.identity && clone.profile.value"
            :model-value="clone.source.value.identity.account"
            :label="clone.profile.value.identity.account.label.toUpperCase()"
            readonly
            :reason="USERNAME_REASON"
          />
        </section>

        <section class="clone-section">
          <h2 class="clone-section__title text-mono">
            RESOURCES
          </h2>
          <GuestResourcesFields
            v-model="clone.resources.value"
            :errors="clone.errors.value"
            disk-locked
            disk-reason="A clone has its source's disk."
          />
        </section>

        <section
          v-if="clone.optionRows.value.length > 0"
          class="clone-section"
        >
          <h2 class="clone-section__title text-mono">
            OPTIONS
          </h2>
          <ProfileOptionField
            v-for="{ option, locked } in clone.optionRows.value"
            :key="option.key"
            :option="option"
            :model-value="clone.options.value[option.key]"
            :locked="locked"
            :locked-reason="LOCKED_REASON"
            :error="clone.errors.value[`options.${option.key}`]"
            @update:model-value="(value) => clone.setOption(option.key, value)"
          />
        </section>

        <GuestNotice tone="warning">
          {{ blockingWarning('clone') }}
        </GuestNotice>
        <GuestNotice
          v-if="clone.submission.banner.value"
          tone="error"
        >
          {{ clone.submission.banner.value }}
        </GuestNotice>

        <div class="clone-actions">
          <q-btn
            outline
            square
            type="submit"
            label="[CLONE]"
            class="clone-submit text-mono"
            :loading="clone.submission.submitting.value"
            :disable="!clone.canSubmit.value || clone.submission.submitting.value"
          />
        </div>
      </form>
    </ViewState>
  </div>
</template>

<style scoped>
.clone-page {
  max-width: 48rem;
  padding: var(--spacing-lg);
}

.clone-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-lg);
}

.section-title {
  min-width: 0;
  margin: 0;
  color: var(--blue-primary);
  font-size: 0.9rem;
  /* Quasar's typography gives h1 a 6rem line-height, which shrinking the font doesn't undo. */
  line-height: 1.2;
  letter-spacing: 2px;
  overflow-wrap: anywhere;
}

.clone-header__source {
  color: var(--text-white);
}

.clone-cancel {
  margin-left: auto;
  padding-right: 0;
  color: var(--text-gray);
}

.clone-unavailable {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--spacing-md);
}

.clone-back {
  color: var(--blue-primary);
}

.clone-form {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
}

.clone-summary {
  margin: 0;
  color: var(--text-gray-light);
}

.clone-section {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  min-width: 0;
}

.clone-section__title {
  margin: 0;
  line-height: 1.2;
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.clone-submit {
  color: var(--blue-primary);
}
</style>
