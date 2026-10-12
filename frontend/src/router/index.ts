import { defineRouter } from '#q-app'
import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'
import { routes } from './routes'

export function createAppRouter(history: RouterHistory) {
  return createRouter({
    scrollBehavior: () => ({ left: 0, top: 0 }),
    routes,
    history,
  })
}

export default defineRouter(() => createAppRouter(createWebHistory(import.meta.env.QUASAR_VUE_ROUTER_BASE)))
