import vue from '@vitejs/plugin-vue'
import { quasar } from '@quasar/vite-plugin'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue(), quasar()],
  resolve: {
    alias: {
      '#q-app': '@quasar/app-vite',
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'happy-dom',
    include: ['tests/unit/**/*.test.ts'],
    restoreMocks: true,
  },
})
