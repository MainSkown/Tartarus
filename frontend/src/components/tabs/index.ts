import { defineAsyncComponent, type Component } from 'vue'

/** The view of each exploring tab, loaded only when its tab is opened. */
export const TAB_VIEWS: Record<string, Component> = {
  processes: defineAsyncComponent(() => import('./ProcessesTab.vue')),
  network: defineAsyncComponent(() => import('./NetworkTab.vue')),
  artifacts: defineAsyncComponent(() => import('./ArtifactsTab.vue')),
  detections: defineAsyncComponent(() => import('./DetectionsTab.vue')),
}
