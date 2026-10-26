<script setup lang="ts">
import { useAppVersion } from '@/composables/use-app-version'
import { t } from '@/i18n'

const REPOSITORY_FILES_URL = 'https://github.com/MainSkown/Tartarus/blob/master'
const LICENSE_URL = `${REPOSITORY_FILES_URL}/LICENSE`
const THIRD_PARTY_URL = `${REPOSITORY_FILES_URL}/THIRD_PARTY.md`
const ATTACK_TERMS_URL = 'https://attack.mitre.org/resources/legal-and-branding/terms-of-use/'

const { state, reload } = useAppVersion()
</script>

<template>
  <q-card
    flat
    square
    class="about-card"
  >
    <h2 class="about-title text-mono">
      {{ t('settings.about.title') }}
    </h2>

    <div
      v-if="state.status === 'loading'"
      class="about-state"
    >
      <span
        class="loader"
        role="status"
        :aria-label="t('settings.about.loading')"
      />
    </div>

    <div
      v-else-if="state.status === 'failed'"
      class="about-state text-mono"
    >
      <p class="text-gray">
        {{ t('settings.about.loadFailed') }}
      </p>
      <q-btn
        outline
        square
        :label="t('common.retry')"
        class="about-retry-btn text-mono"
        @click="reload"
      />
    </div>

    <div
      v-else
      class="about-body"
    >
      <p class="about-name text-mono">
        {{ t('settings.about.name') }}
      </p>
      <dl class="about-rows text-mono">
        <dt>{{ t('settings.about.version') }}</dt>
        <dd class="about-version">
          {{ state.info.version }}
        </dd>

        <template v-if="state.info.commit">
          <dt>{{ t('settings.about.commit') }}</dt>
          <dd class="about-commit">
            {{ state.info.commit }}
          </dd>
        </template>

        <dt>{{ t('settings.about.license') }}</dt>
        <dd>
          <span class="about-license">{{ state.info.license }}</span>
          <a
            :href="LICENSE_URL"
            class="about-license-link"
            target="_blank"
            rel="noopener noreferrer"
          >{{ t('settings.about.viewLicense') }}</a>
        </dd>
      </dl>
      <a
        :href="THIRD_PARTY_URL"
        class="about-third-party-link text-mono"
        target="_blank"
        rel="noopener noreferrer"
      >{{ t('settings.about.thirdParty') }}</a>
      <p class="about-attribution text-mono text-gray">
        {{ t('settings.about.attribution') }}
        <a
          :href="ATTACK_TERMS_URL"
          class="about-attribution-link"
          target="_blank"
          rel="noopener noreferrer"
        >{{ t('settings.about.attackTerms') }}</a>
      </p>
    </div>
  </q-card>
</template>

<style scoped>
.about-card {
  background: var(--dark-bg);
  border: 2px solid var(--border-primary);
  padding: var(--spacing-lg);
}

.about-title {
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  /* Quasar's typography gives h2 a tall line-height, which would leave a gap above the rows. */
  line-height: 1.2;
  letter-spacing: 1px;
  margin: 0 0 var(--spacing-md);
}

.about-state {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--spacing-md);
  padding: var(--spacing-md) 0;
}

.about-body {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.about-name {
  margin: 0;
  font-size: 0.9rem;
  font-weight: bold;
}

.about-rows {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: var(--spacing-sm) var(--spacing-lg);
  margin: 0;
  font-size: 0.8rem;
}

.about-rows dt {
  color: var(--text-gray);
  letter-spacing: 1px;
}

.about-rows dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.about-license-link {
  display: block;
  margin-top: var(--spacing-xs);
  color: var(--blue-primary);
}

.about-attribution {
  margin: 0;
  font-size: 0.7rem;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.about-attribution-link {
  display: block;
  margin-top: var(--spacing-xs);
  color: var(--blue-primary);
  letter-spacing: 1px;
}

.about-third-party-link {
  align-self: flex-start;
  color: var(--blue-primary);
  font-size: 0.75rem;
  letter-spacing: 1px;
}
</style>
