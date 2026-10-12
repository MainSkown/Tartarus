import type { RouteRecordRaw } from 'vue-router'

// All routes render under the shared app shell (MainLayout: header, health dots, mini nav
// drawer - gui spec "App shell"). None of these pages have real content yet; each renders
// the shared PlaceholderPage until the milestone that builds it does so (F9 replaces
// /settings next).
export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: [
      { path: '', name: 'dashboard', component: () => import('@/pages/PlaceholderPage.vue') },
      {
        // One route covers both /analyses/:id (defaults to no tab) and /analyses/:id/:tab.
        path: 'analyses/:id/:tab?',
        name: 'analysis-workspace',
        component: () => import('@/pages/PlaceholderPage.vue'),
      },
      { path: 'rules', name: 'rules', component: () => import('@/pages/PlaceholderPage.vue') },
      { path: 'guest', name: 'guest', component: () => import('@/pages/PlaceholderPage.vue') },
      // Placeholder only: F9 (the very next subtask) swaps this entry for the real Settings
      // page that reads/writes GET/PUT /settings.
      { path: 'settings', name: 'settings', component: () => import('@/pages/PlaceholderPage.vue') },
      {
        path: ':pathMatch(.*)*',
        name: 'not-found',
        component: () => import('@/pages/PlaceholderPage.vue'),
      },
    ],
  },
]
