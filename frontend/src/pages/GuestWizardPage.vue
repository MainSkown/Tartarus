<script setup lang="ts">
import GuestField from '@/components/guest/GuestField.vue'
import GuestIdentityField from '@/components/guest/GuestIdentityField.vue'
import GuestMediaList from '@/components/guest/GuestMediaList.vue'
import GuestNameField from '@/components/guest/GuestNameField.vue'
import GuestNotice from '@/components/guest/GuestNotice.vue'
import GuestResourcesFields from '@/components/guest/GuestResourcesFields.vue'
import ProfileOptionField from '@/components/guest/ProfileOptionField.vue'
import ViewState from '@/components/ViewState.vue'
import { useGuestWizard } from '@/composables/use-guest-wizard'
import { blockingWarning } from '@/services/guest-wizard-view'

const wizard = useGuestWizard()
void wizard.load()
</script>

<template>
  <div class="wizard-page">
    <div class="wizard-header">
      <h1 class="section-title text-mono">
        BUILD GUEST
      </h1>
      <q-btn
        flat
        square
        label="[CANCEL]"
        class="wizard-cancel text-mono"
        to="/guest"
      />
    </div>

    <q-stepper
      v-model="wizard.step.value"
      vertical
      flat
      dark
      header-nav
      class="wizard-stepper"
    >
      <q-step
        :name="1"
        title="CHOOSE MEDIA"
        caption="The installation image to build from"
        icon="album"
        :done="wizard.step.value > 1"
        :header-nav="wizard.step.value > 1"
      >
        <ViewState
          :loading="wizard.mediaStatus.value === 'loading'"
          :error="wizard.mediaStatus.value === 'failed' ? wizard.mediaError.value : undefined"
          @retry="wizard.load"
        >
          <GuestMediaList
            :choices="wizard.mediaChoices.value"
            :selected="wizard.selectedMedia.value?.file"
            :error="wizard.errors.value['media.file']"
            @select="wizard.selectMedia"
            @reload="wizard.load"
          />
        </ViewState>
        <q-stepper-navigation>
          <q-btn
            outline
            square
            label="[CONTINUE]"
            class="wizard-primary text-mono"
            :disable="!wizard.canContinue.value"
            @click="wizard.next"
          />
        </q-stepper-navigation>
      </q-step>

      <q-step
        :name="2"
        title="SETTINGS"
        caption="What the guest is called, who it is and what it has"
        icon="tune"
        :done="wizard.step.value > 2"
        :header-nav="wizard.step.value > 2"
      >
        <div
          v-if="wizard.profile.value"
          class="settings"
        >
          <section class="settings__section">
            <h2 class="settings__title text-mono">
              GUEST
            </h2>
            <GuestNameField
              v-model="wizard.name.value"
              :error="wizard.errors.value.name"
            />
            <q-select
              v-if="wizard.variantChoices.value.length > 0"
              v-model="wizard.variantIndex.value"
              :options="wizard.variantChoices.value"
              :error="Boolean(wizard.errors.value['media.variant'])"
              :error-message="wizard.errors.value['media.variant']"
              option-value="value"
              option-label="label"
              emit-value
              map-options
              label="EDITION"
              outlined
              dense
              square
              dark
              hide-bottom-space
              stack-label
              class="settings__edition text-mono"
            />
          </section>

          <section class="settings__section">
            <h2 class="settings__title text-mono">
              INSIDE THE GUEST
            </h2>
            <GuestIdentityField
              v-model="wizard.account.value"
              :label="wizard.profile.value.identity.account.label.toUpperCase()"
              :error="wizard.errors.value['identity.account']"
              hint="A realistic one is chosen when this is left blank."
            />
            <GuestIdentityField
              v-model="wizard.machine.value"
              :label="wizard.profile.value.identity.machine.label.toUpperCase()"
              :error="wizard.errors.value['identity.machine']"
              hint="A realistic one is chosen when this is left blank."
            />
            <GuestIdentityField
              v-model="wizard.password.value"
              :label="wizard.profile.value.identity.password.label.toUpperCase()"
              :error="wizard.errors.value['identity.password']"
              hint="A random one is chosen when this is left blank; the Guest page shows it."
              secret
            />
          </section>

          <section class="settings__section">
            <h2 class="settings__title text-mono">
              RESOURCES
            </h2>
            <GuestResourcesFields
              v-model="wizard.resources.value"
              :errors="wizard.errors.value"
              :min-disk="wizard.profile.value.resources.min_disk_gb"
            />
          </section>

          <section
            v-if="wizard.profile.value.options.length > 0"
            class="settings__section"
          >
            <h2 class="settings__title text-mono">
              OPTIONS
            </h2>
            <ProfileOptionField
              v-for="option in wizard.profile.value.options"
              :key="option.key"
              :option="option"
              :model-value="wizard.options.value[option.key]"
              :error="wizard.errors.value[`options.${option.key}`]"
              @update:model-value="(value) => wizard.setOption(option.key, value)"
            />
          </section>
        </div>
        <q-stepper-navigation class="wizard-navigation">
          <q-btn
            flat
            square
            label="[BACK]"
            class="wizard-back text-mono"
            @click="wizard.back"
          />
          <q-btn
            outline
            square
            label="[CONTINUE]"
            class="wizard-primary text-mono"
            :disable="!wizard.canContinue.value"
            @click="wizard.next"
          />
        </q-stepper-navigation>
      </q-step>

      <q-step
        :name="3"
        title="REVIEW"
        caption="Check it, then build"
        icon="fact_check"
      >
        <dl class="review">
          <GuestField
            v-for="row in wizard.reviewRows.value"
            :key="row.label"
            :label="row.label.toUpperCase()"
          >
            <span
              class="review__value text-mono"
              :class="{ 'review__value--blank': row.blank }"
            >{{ row.value }}</span>
          </GuestField>
        </dl>
        <GuestNotice
          tone="warning"
          class="wizard-notice"
        >
          {{ blockingWarning('build') }}
        </GuestNotice>
        <GuestNotice
          v-if="wizard.submission.banner.value"
          tone="error"
          class="wizard-notice"
        >
          {{ wizard.submission.banner.value }}
        </GuestNotice>
        <q-stepper-navigation class="wizard-navigation">
          <q-btn
            flat
            square
            label="[BACK]"
            class="wizard-back text-mono"
            :disable="wizard.submission.submitting.value"
            @click="wizard.back"
          />
          <q-btn
            outline
            square
            label="[BUILD GUEST]"
            class="wizard-primary text-mono"
            :loading="wizard.submission.submitting.value"
            :disable="!wizard.canContinue.value || wizard.submission.submitting.value"
            @click="wizard.submit"
          />
        </q-stepper-navigation>
      </q-step>
    </q-stepper>
  </div>
</template>

<style scoped>
.wizard-page {
  max-width: 60rem;
  padding: var(--spacing-lg);
}

.wizard-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-lg);
}

.section-title {
  color: var(--blue-primary);
  font-size: 0.9rem;
  /* Quasar's typography gives h1 a 6rem line-height, which shrinking the font doesn't undo. */
  line-height: 1.2;
  letter-spacing: 2px;
  margin: 0;
}

.wizard-cancel,
.wizard-back {
  color: var(--text-gray);
}

.wizard-back {
  padding-left: 0;
}

.wizard-cancel {
  padding-right: 0;
}

.wizard-primary {
  color: var(--blue-primary);
}

.wizard-stepper {
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
}

.wizard-stepper :deep(.q-stepper__title) {
  font-family: var(--font-mono);
  font-size: 0.85rem;
  letter-spacing: 1px;
}

.wizard-stepper :deep(.q-stepper__caption) {
  color: var(--text-gray);
}

.wizard-stepper :deep(.q-stepper__dot) {
  border-radius: 0;
}

.wizard-stepper :deep(.q-stepper__step-inner) {
  min-width: 0;
}

.wizard-navigation {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-sm);
}

.settings {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
  max-width: 44rem;
}

.settings__section {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  min-width: 0;
}

.settings__title {
  margin: 0;
  /* Quasar's typography gives h2 a tall line-height, which shrinking the font doesn't undo. */
  line-height: 1.2;
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.review {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  margin: 0 0 var(--spacing-md);
  max-width: 44rem;
}

/* Option labels come from the profile and run longer than the card's field names. */
.review :deep(.guest-field) {
  grid-template-columns: 10rem minmax(0, 1fr);
}

.review__value--blank {
  color: var(--text-gray);
  font-style: italic;
}

.wizard-notice {
  max-width: 44rem;
  margin-bottom: var(--spacing-sm);
}
</style>
