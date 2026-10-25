# G3 notes (browser origin and response headers)

## Done
- backend: app/browser_guard.py (BrowserOriginGuard: 421 foreign Host, 403 / WS close 1008 foreign Origin on non-safe HTTP and WS; SecurityHeaders: nosniff, no-referrer, X-Frame-Options DENY, CSP frame-ancestors 'none' on every response), wired in app/main.py; Settings.tartarus_allowed_hosts (env TARTARUS_ALLOWED_HOSTS, comma separated, added to localhost/127.0.0.1/[::1]/backend); tests/test_browser_guard.py; conftest settings allow Host test/testserver; two create_app() wiring tests now take the app fixture.
- compose: TARTARUS_ALLOWED_HOSTS passed to backend; .env.example documents it.
- nginx.conf: server_tokens off; maps $host_allowed / $origin_foreign / $refuse_origin / $cache_control; 421 and 403 rules; security headers + CSP at server level only (Cache-Control moved to a map so no location has add_header); tests/test_nginx_security.py; syntax checked with docker nginx -t; behaviour probed with a throwaway container (removed).
- frontend: encodeURIComponent in GuestCard.vue and ArtifactTable.vue, Object.hasOwn in services/lanes.ts, eslint vue/no-v-html error, quasar.config.ts allowedHosts ['localhost'] (verified: foreign Host 403, 127.0.0.1 and localhost 200).

## Decisions
- Backend compares host names only (Host loses its port behind nginx, dev server proxies from :5173). nginx compares Origin to http://$http_host exactly (port included).
- CSP keeps style-src 'unsafe-inline' (Quasar/Vue inline styles; not verified that it could be dropped). No inline scripts in dist/pwa/index.html, so script-src 'self'.
- nginx host allowlist is fixed to loopback; a LAN-named install must edit the map in frontend/nginx.conf as well as set TARTARUS_ALLOWED_HOSTS.

## Next
- final check run results reported to caller
