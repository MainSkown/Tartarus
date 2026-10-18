import { defineConfig } from '#q-app'

const apiProxyTarget = process.env.API_PROXY_TARGET ?? 'http://backend:8000'
// Overridable so the Playwright screenshot harness (frontend/playwright.config.ts) can run its
// own dev server instance on a different port than the Docker dev stack's 5173, in case both
// are ever up on the same host at once.
const devServerPort = Number(process.env.DEV_SERVER_PORT ?? 5173)

export default defineConfig(() => ({
  boot: ['i18n', 'notify', 'api'],

  css: ['app.css'],

  extras: ['material-icons', 'material-icons-outlined'],

  build: {
    target: {
      browser: ['es2022', 'firefox115', 'chrome115', 'safari14'],
      node: 'node22',
    },
    vueRouterMode: 'history',
    typescript: {
      strict: true,
      vueShim: true,
      // `exactOptionalPropertyTypes` fails vue-tsc on src/api/'s vendored client runtime
      // (@hey-api/openapi-ts v0.99.0's bundled fetch-client core, not our schema-derived
      // types or SDK functions, which both pass clean) under TypeScript ~6.0.3.
      // `exclude` alone can't fix this: vue-tsc still type-checks any excluded file that's
      // reachable through an import, which src/boot/api.ts's import of `client` requires.
      // Turning the one flag off project-wide is the smallest fix available without hand-
      // editing generator-owned output (never done per CLAUDE.md rule 3) or splitting the
      // build into TS project references for one directory.
      extendTsConfig(tsConfig) {
        tsConfig.compilerOptions ??= {}
        tsConfig.compilerOptions.exactOptionalPropertyTypes = false
      },
    },
  },

  devServer: {
    host: '0.0.0.0',
    port: devServerPort,
    open: false,
    proxy: {
      '/api': { target: apiProxyTarget, changeOrigin: true },
      '/ws': { target: apiProxyTarget, changeOrigin: true, ws: true },
    },
  },

  framework: {
    config: { dark: true },
    lang: 'en-US',
    plugins: ['Notify', 'Dialog', 'Loading', 'LocalStorage'],
  },

  animations: [],

  pwa: {
    workboxMode: 'GenerateSW',
    // The scaffold default links apple-touch icons and a pinned-tab SVG that this app does not ship.
    injectPWAMetaTags: ({ pwaManifest, publicPath }) =>
      `<meta name="theme-color" content="${pwaManifest.theme_color}">` +
      `<link rel="apple-touch-icon" href="${publicPath}icons/icon-192x192.png">`,
    extendPWAGenerateSWOptions(config) {
      // Only the app shell is precached; /api and /ws must always reach the network.
      config.navigateFallbackDenylist = [/^\/api\//, /^\/ws\//]
      config.runtimeCaching = []
    },
  },
}))
