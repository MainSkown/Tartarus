<script setup lang="ts">
import type { ExtractedConfig } from '@/api'

defineProps<{ configs: ExtractedConfig[] }>()
</script>

<template>
  <section
    v-for="config in configs"
    :key="config.id"
    class="artifact-config"
  >
    <h3 class="config-family text-mono">
      {{ config.family }}
    </h3>
    <pre class="code-block">{{ JSON.stringify(config.data, null, 2) }}</pre>
  </section>
</template>

<style scoped>
.config-family {
  margin: 0 0 var(--spacing-xs);
  color: var(--blue-primary);
  font-size: 0.75rem;
  letter-spacing: 1px;
}

.artifact-config + .artifact-config {
  margin-top: var(--spacing-md);
}

.code-block {
  margin: 0;
  font-size: 0.85rem;
}
</style>
