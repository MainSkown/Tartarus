import { defineConfig } from '#q-app'

const apiProxyTarget = process.env.API_PROXY_TARGET ?? 'http://backend:8000'

export default defineConfig(() => ({
  boot: ['notify'],

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
    },
  },

  devServer: {
    host: '0.0.0.0',
    port: 5173,
    open: false,
    proxy: {
      '/api': { target: apiProxyTarget, changeOrigin: true },
      '/ws': { target: apiProxyTarget, changeOrigin: true, ws: true },
    },
  },

  framework: {
    config: { dark: true },
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
