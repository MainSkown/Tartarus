<script setup lang="ts">
import { computed } from 'vue'
import { laneMeta } from '@/services/lanes'

const props = defineProps<{ lane: string }>()

const meta = computed(() => laneMeta(props.lane))
</script>

<template>
  <q-icon
    :name="meta.icon"
    size="16px"
    :style="{ color: `var(${meta.color})` }"
    aria-hidden="true"
  />
</template>
