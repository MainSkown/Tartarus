import type { RouteRecordRaw } from 'vue-router'

export const routes: RouteRecordRaw[] = [
  {
    path: '/:pathMatch(.*)*',
    name: 'placeholder',
    component: () => import('@/pages/PlaceholderPage.vue'),
  },
]
