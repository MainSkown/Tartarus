<script setup lang="ts">
import type { RuleDetail, RuleRead } from '@/api'
import CopyButton from '@/components/CopyButton.vue'
import PaneHeading from '@/components/PaneHeading.vue'
import SeverityBadge from '@/components/SeverityBadge.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import ViewState from '@/components/ViewState.vue'
import { severityOfLevel, validityMeta } from '@/services/rule-view'

defineProps<{ rule: RuleRead; detail: RuleDetail | undefined; loading: boolean; error: string | undefined }>()
const emit = defineEmits<{ close: []; retry: [] }>()
</script>

<template>
  <article class="rule-detail">
    <div class="rule-detail__bar">
      <PaneHeading
        class="rule-detail__heading"
        label="RULE"
      />
      <button
        type="button"
        class="rule-detail__close text-mono"
        @click="emit('close')"
      >
        [CLOSE]
      </button>
    </div>

    <div class="rule-detail__badges">
      <SeverityBadge
        v-if="severityOfLevel(rule.level)"
        :severity="severityOfLevel(rule.level)!"
      />
      <StatusBadge :validity="rule.validity" />
    </div>
    <h2 class="rule-detail__title text-mono">
      {{ rule.title }}
    </h2>
    <p class="rule-detail__description">
      {{ rule.description ?? 'no description' }}
    </p>

    <div
      v-if="rule.validity !== 'valid'"
      class="rule-detail__error"
      role="alert"
      :style="{ '--problem-color': `var(${validityMeta(rule.validity).color})` }"
    >
      <q-icon
        :name="validityMeta(rule.validity).icon"
        size="20px"
        aria-hidden="true"
      />
      <div>
        <p class="rule-detail__error-label text-mono">
          {{ validityMeta(rule.validity).label }}
        </p>
        <p class="rule-detail__error-text text-mono">
          {{ rule.error ?? 'no reason was recorded' }}
        </p>
      </div>
    </div>

    <dl class="rule-detail__facts">
      <dt class="text-mono">
        ID
      </dt>
      <dd class="text-mono">
        {{ rule.id }}<CopyButton
          :text="rule.id"
          what="rule id"
        />
      </dd>
      <dt class="text-mono">
        PATH
      </dt>
      <dd class="text-mono">
        {{ rule.path }}<CopyButton
          :text="rule.path"
          what="rule path"
        />
      </dd>
      <dt class="text-mono">
        LOGSOURCE
      </dt>
      <dd class="text-mono">
        {{ rule.logsource_category ?? '–' }}
      </dd>
      <dt class="text-mono">
        STATUS
      </dt>
      <dd class="text-mono">
        {{ rule.status ?? '–' }}
      </dd>
      <template v-if="rule.tags.length > 0">
        <dt class="text-mono">
          TAGS
        </dt>
        <dd class="text-mono">
          {{ rule.tags.join(' ') }}
        </dd>
      </template>
    </dl>

    <div class="rule-detail__yaml-bar">
      <h3 class="rule-detail__yaml-heading text-mono">
        YAML
      </h3>
      <CopyButton
        v-if="detail"
        :text="detail.yaml"
        what="rule YAML"
      />
    </div>
    <ViewState
      :loading="loading"
      :error="error"
      @retry="emit('retry')"
    >
      <pre
        v-if="detail"
        class="code-block rule-detail__yaml"
        tabindex="0"
        aria-label="Rule YAML"
      >{{ detail.yaml.trimEnd() }}</pre>
    </ViewState>
  </article>
</template>

<style scoped>
.rule-detail {
  min-width: 0;
}

.rule-detail__bar {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  border-bottom: 2px solid var(--border-primary);
}

.rule-detail__heading {
  flex: 1;
  min-width: 0;
  margin: 0;
  border-bottom: none;
}

.rule-detail__close {
  padding: var(--spacing-xs) var(--spacing-sm);
  border: none;
  background: transparent;
  color: var(--blue-primary);
  font-size: 0.75rem;
  letter-spacing: 1px;
  cursor: pointer;
}

.rule-detail__close:hover,
.rule-detail__close:focus-visible {
  color: var(--blue-hover);
}

.rule-detail__badges {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-sm);
  padding-top: var(--spacing-sm);
}

.rule-detail__title {
  margin: var(--spacing-sm) 0;
  font-size: 1.1rem;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.rule-detail__description {
  margin: 0 0 var(--spacing-md);
  overflow-wrap: anywhere;
}

.rule-detail__error {
  display: flex;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-md);
  padding: var(--spacing-sm) var(--spacing-md);
  border: 2px solid var(--problem-color);
  border-left-width: 6px;
  background: color-mix(in srgb, var(--problem-color) 10%, var(--black));
  color: var(--problem-color);
}

.rule-detail__error p {
  margin: 0;
}

.rule-detail__error-label {
  font-size: 0.75rem;
  font-weight: bold;
  letter-spacing: 2px;
}

.rule-detail__error-text {
  color: var(--text-white);
  font-size: 0.85rem;
  overflow-wrap: anywhere;
}

.rule-detail__facts {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: var(--spacing-xs) var(--spacing-md);
  margin: 0;
}

.rule-detail__facts dt {
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.rule-detail__facts dd {
  margin: 0;
  font-size: 0.85rem;
  overflow-wrap: anywhere;
}

.rule-detail__yaml-bar {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  margin: var(--spacing-lg) 0 var(--spacing-sm);
}

.rule-detail__yaml-heading {
  margin: 0;
  color: var(--blue-primary);
  font-size: 0.75rem;
  line-height: 1.2;
  letter-spacing: 2px;
}

.rule-detail__yaml {
  max-height: clamp(10rem, calc(100vh - 30rem), 28rem);
  margin: 0;
  overflow: auto;
  font-size: 0.85rem;
  tab-size: 4;
}

.rule-detail__yaml:focus-visible {
  outline: 2px solid var(--blue-light);
  outline-offset: 2px;
}
</style>
