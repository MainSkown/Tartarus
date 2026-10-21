<script setup lang="ts">
import { computed } from 'vue'
import type { IocType } from '@/api'
import { useIocAnalyses } from '@/composables/use-ioc-analyses'
import { t } from '@/i18n'
import { formatCount } from '@/services/format-number'

const props = defineProps<{ kind: IocType; value: string }>()

const state = useIocAnalyses(
  () => props.kind,
  () => props.value,
)

const seenIn = computed(() => (state.value.status === 'seen' ? state.value.analyses : undefined))
</script>

<template>
  <span
    v-if="state.status === 'failed'"
    class="ioc-analyses__failed text-gray"
    role="img"
    :aria-label="t('iocs.analyses.failed')"
    :title="t('iocs.analyses.failed')"
  >
    <q-icon
      name="link_off"
      size="14px"
    />
  </span>
  <q-btn
    v-else-if="seenIn"
    flat
    dense
    no-caps
    square
    aria-haspopup="menu"
    class="ioc-analyses__chip text-mono"
    :label="t('iocs.analyses.chip', { count: formatCount(seenIn.length) }, seenIn.length)"
  >
    <q-menu
      anchor="bottom left"
      self="top left"
      class="ioc-analyses__popup"
    >
      <q-list
        dense
        class="ioc-analyses__menu"
        :aria-label="t('iocs.analyses.menuLabel')"
      >
        <q-item
          v-for="hit in seenIn"
          :key="hit.analysis_id"
          v-close-popup
          clickable
          :to="`/analyses/${hit.analysis_id}`"
          class="text-mono"
        >
          <q-item-section>{{ t('iocs.analyses.analysis', { id: hit.analysis_id }) }}</q-item-section>
          <q-item-section side>
            {{ t('iocs.analyses.eventCount', { count: formatCount(hit.count) }, hit.count) }}
          </q-item-section>
        </q-item>
      </q-list>
    </q-menu>
  </q-btn>
</template>

<style scoped>
.ioc-analyses__chip {
  flex: none;
  height: 20px;
  min-height: 0;
  margin-left: var(--spacing-xs);
  padding: 0 var(--spacing-xs);
  border: 1px solid var(--border-secondary);
  color: var(--blue-light);
  font-size: 0.7rem;
  line-height: 1;
  vertical-align: middle;
}

.ioc-analyses__chip :deep(.q-btn__content) {
  line-height: 1;
}

/* Quasar places the menu on the side with room; the list scrolls inside it, so all analyses stay reachable. */
.ioc-analyses__popup {
  max-height: min(45vh, 360px);
  overflow-y: auto;
}

.ioc-analyses__failed {
  display: inline-flex;
  margin-left: var(--spacing-xs);
  vertical-align: middle;
}
</style>
