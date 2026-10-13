<script setup lang="ts">
import { computed } from 'vue'
import type { ProcessNode } from '@/api'
import ProcessChip from '@/components/ProcessChip.vue'
import SeverityBadge from '@/components/SeverityBadge.vue'
import { flattenProcesses, toTreeNodes, type TreeNode } from '@/services/process-graph'

const props = defineProps<{ roots: ProcessNode[]; selectedId?: string }>()
const emit = defineEmits<{ select: [entityId: string] }>()

const nodes = computed(() => toTreeNodes(props.roots))
const expanded = computed(() => flattenProcesses(props.roots).map((process) => process.entity_id))

function select(key: string | null): void {
  if (key !== null) emit('select', key)
}
</script>

<template>
  <q-tree
    :nodes="nodes"
    node-key="key"
    :selected="selectedId ?? null"
    :expanded="expanded"
    no-selection-unset
    no-connectors
    class="process-tree-list text-mono"
    @update:selected="select"
  >
    <template #default-header="{ node }: { node: TreeNode }">
      <div class="process-tree-list__row">
        <ProcessChip :process="node.process" />
        <SeverityBadge
          v-if="node.process.max_severity && node.process.detection_count > 0"
          :severity="node.process.max_severity"
          :count="node.process.detection_count"
        />
      </div>
    </template>
  </q-tree>
</template>

<style scoped>
.process-tree-list {
  min-width: 0;
  padding: var(--spacing-sm);
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
  max-height: clamp(420px, 65vh, 720px);
  overflow: auto;
}

.process-tree-list :deep(.q-tree__node--selected) {
  background: var(--hover-bg);
  box-shadow: inset 0 0 0 2px var(--blue-light), var(--shadow-blue-weak);
}

.process-tree-list__row {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  min-width: 0;
}
</style>
