import type { RouteRecordRaw } from 'vue-router'

// All routes render under the shared app shell (MainLayout: header, health dots, mini nav
// drawer - gui spec "App shell"). Each renders the shared PlaceholderPage until the milestone
// that builds it does so.
export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: [
      { path: '', name: 'dashboard', component: () => import('@/pages/DashboardPage.vue') },
      {
        // One route covers both /analyses/:id (defaults to no tab) and /analyses/:id/:tab.
        path: 'analyses/:id/:tab?',
        name: 'analysis-workspace',
        component: () => import('@/pages/AnalysisPage.vue'),
      },
      { path: 'rules', name: 'rules', component: () => import('@/pages/RulesPage.vue') },
      { path: 'guest', name: 'guest', component: () => import('@/pages/PlaceholderPage.vue') },
      { path: 'settings', name: 'settings', component: () => import('@/pages/SettingsPage.vue') },
      {
        path: ':pathMatch(.*)*',
        name: 'not-found',
        component: () => import('@/pages/PlaceholderPage.vue'),
      },
    ],
  },
]
