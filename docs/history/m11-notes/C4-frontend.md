# C4 - Frontend security review (frontend/src, Vue 3 + Quasar)

Status: DONE (all 7 areas audited). Read-only on source. Reviewed: working tree on branch `ci`, `frontend/dist/pwa` build output, plus the backend ws/download handlers where the frontend relies on them.

Done: 1 XSS sinks, 2 links/downloads, 3 WebSocket/Guacamole, 4 client storage, 5 PWA, 6 API client path handling, 7 build config.
In progress: none.
Next: nothing; findings below need triage.

## Verdict

No exploitable XSS found. Malware-controlled strings reach the DOM only through Vue text interpolation, `:title`, `:alt` and `<textarea>` bindings, or a canvas (cytoscape, Timeline). The weak points are defence in depth: no CSP or security headers, and no Origin check on the desktop WebSocket (backend side).

---

## 1. XSS sinks - checked, nothing found

Checked (grep over `src/**/*.vue|ts`, excluding generated `src/api/` and tests):
- `v-html`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval(`, `new Function`, `srcdoc`, `iframe`, `dangerouslySetInnerHTML`, markdown libs (`marked`, `markdown`, DOMPurify): zero hits. The only dynamic DOM construction is `document.createElement('a')` in `services/download.ts:25` and `components/ProcessGraph.vue:81` (anchor `href`/`download` set from a blob URL or cytoscape PNG data URL, not from data).
- Notes: `NoteEditor.vue:72` renders in a `q-input type="textarea"`; `NotesTab.vue` lists notes through text interpolation. There is no markdown rendering.
- Quasar `Notify.create` calls (all 14 sites): none passes `html: true`, so messages and captions are text. `error.error.message` and `captions` in `boot/api.ts:35-39` (server messages that can echo user data) are also text.
- Timeline tooltip: `services/timeline-tooltip.ts` builds plain `{label, value}` rows (process name, file path, registry path, URL, DNS, API name). `Timeline.vue:353-381` renders them with `{{ }}`. Not an HTML builder. The canvas drawing in `timeline-draw.ts` uses `fillText`.
- Process graph: labels are cytoscape `data.label` rendered on canvas. No selector strings are built from data (`graph.elements().remove()` only).
- Query bar mirror (`QueryBar.vue:177`) renders segments via text interpolation, with no HTML.
- vue-i18n: no `@html`, `<i18n>` blocks or `warnHtmlMessage` use. Attacker strings are passed as named parameters (`t('...', { name })`) and rendered as text.
- Dynamic `:style`: every one is `var(${meta.color})` where `meta.color` comes from fixed lookup tables (`laneMeta`, `severityMeta`, `validityMeta`, headline). No data-derived CSS.
- Dynamic `:href` / `:src` / `:to`:
  - `:src` is `screenshotUrl(analysisId, n)` with numeric ids only (`ScreenshotStrip.vue:45`, `ScreenshotLightbox.vue:54`, `LiveFinishedPanel.vue:41`, `DesktopMessage.vue:24`).
  - `:href` is `downloadUrl(artifact)` (`ArtifactTable.vue:17,125`). It uses `analysisId` and `artifact.id` (a server id) in the path; `artifact.id` is not URI-encoded, see F4.
  - `:href="pcapUrl"` (`NetworkTab.vue:152,196`) uses a numeric id.
  - `DetectionDetail.vue:88` is the only data-bound `href` (rule `references`). It is guarded by `WEB_ADDRESS = /^https?:\/\//i` (line 17), so `javascript:` and `data:` URLs fall to a plain `<span>`. Good.

## 2. Links, downloads, blob URLs

- `target="_blank"` appears once (`DetectionDetail.vue:89`) with `rel="noopener noreferrer"`. OK. There are no IOC hyperlinks built from data; IOC values only go into router links or API path params.
- `services/download.ts`: blob URL, `anchor.download = filename`, revoked after 10 s. The filename comes from `Content-Disposition`, with directory parts stripped (`split(/[\\/]/).pop()`). Browsers sanitise `download` names further. No finding. The file name is influenced by malware (artifact name), but the backend wraps it in `download_name(...)` plus `.zip`, and the zip is encrypted (password `infected`).
- Artifact download links (`ArtifactTable.vue:125`) and pcap (`NetworkTab.vue:196`) are plain navigations without the `download` attribute. Safe only because the backend replies `application/zip` / `application/vnd.tcpdump.pcap` with Content-Disposition via `FileResponse(filename=...)` (`backend/app/api/views_findings.py:108,140`). Screenshots are served inline with a media type from a png/jpg whitelist (`views_findings.py:127`). See F3 for the missing `nosniff`.
- ProcessGraph PNG export: `link.href = graph.png(...)` is a cytoscape data URL, not attacker-controlled.

## 3. WebSocket and Guacamole desktop

- `services/ws.ts:19-22`: `resolveWsUrl(path)` builds `ws(s)://${location.host}${path}`, same origin, protocol follows the page. No token, no secret, nothing in the query string. Paths are fixed: `/ws/system`, `/ws/analyses/{numeric id}/live`, and `desktop-url.ts` (`/ws/analyses/{id}/desktop`, `/ws/guests/${encodeURIComponent(name)}/desktop`). Good.
- `desktop-tunnel.ts` is a custom Guacamole tunnel. It sends only keyboard/mouse/ping instructions. Inbound frames go through the Guacamole `Parser` and a try/catch that closes the socket.
- `desktop-session.ts` sets only `onerror`, `onstatechange`, `display.onresize` and mouse/keyboard handlers. It does not set `client.onclipboard`, `onfile`, `onpipe`, `onfilesystem`, `onargv` or `onrequired`. Guest-initiated clipboard, file transfer and pipes are therefore ignored, and the guest can only draw pixels. Good, and worth keeping this way (add a regression test).
- Guacamole error text (`status.message`) is shown via `DesktopMessage.vue` text interpolation only.
- No `postMessage` or `message` listeners anywhere in `src/`.
- Finding: F1 (backend, no Origin check).

## 4. Client storage - checked, nothing found

Only `services/viewer-storage.ts` (try/catch, JSON, validator). Keys: facet-panel open boolean (`use-facet-panel.ts`), chosen event columns (`stores/event-columns.ts`, only `Array.isArray` validated; entries are rendered as field names via text). No secrets, tokens or analysis data. `quasar.config.ts:61` enables the `LocalStorage` plugin but no code calls it. `sessionStorage`, IndexedDB and cookies are not used.

## 5. Service worker / PWA - checked, nothing found

- `quasar.config.ts:71-76`: GenerateSW with `runtimeCaching = []` and `navigateFallbackDenylist = [/^\/api\//, /^\/ws\//]`. The built `dist/pwa/sw.js` precaches only the shell and hashed assets (`index.html`, `manifest.json`, icons, `assets/*`) and registers a single `NavigationRoute` bound to `index.html`. No `/api` response (screenshots, events, IOC data) is cached.
- `src-pwa/register-sw.ts` registers at the default scope `/`. The update notice is a plain toast.
- nginx serves `sw.js`, `index.html` and `manifest.json` with `Cache-Control: no-cache`. Good.
- Minor: after logout-less single-user use there is no sensitive data to retain. If auth is added later, this config stays correct as long as `runtimeCaching` stays empty.

## 6. Generated API client / path injection

- Every request goes through the `@hey-api/openapi-ts` client. Path params go through `encodeURIComponent` (`api/core/utils.gen.ts:76`, `pathSerializer.gen.ts`), so IOC values (URLs, registry keys, with `/`, `?`, `#`) in `iocsAnalyses({ path: { kind, value } })` (`use-ioc-analyses.ts:20`) are safely encoded. Query params (`exportIocs ... query: { format }`) are serialised by the client.
- The only hand-written URLs are the `<a href>` / `<img src>` strings listed in section 1, and the router links below. There is no hand-written `fetch(`.
- Router links with unencoded path segments: F4.

## 7. Build config

- `frontend/dist/pwa` has 0 `*.map` files; Quasar's PWA build does not emit sourcemaps by default and `quasar.config.ts` does not enable them. Good.
- Env vars: `process.env.API_PROXY_TARGET` and `DEV_SERVER_PORT` are read only in `quasar.config.ts` (dev server), not injected into the bundle. `import.meta.env` is used only for `QUASAR_VUE_ROUTER_BASE` and `QUASAR_SERVICE_WORKER_FILE`. No secrets in the client bundle.
- Dockerfile: multi-stage; `npm ci --ignore-scripts` (good for supply chain); production stage is `nginx:alpine` serving only `dist/pwa`.
- nginx: F2.

---

## Findings

### F1 - medium - Desktop and live WebSockets accept any Origin (cross-site WebSocket hijacking)
- Where: `backend/app/ws/desktop.py:130` (`websocket.accept(...)` with no Origin check; same for `ws/live.py:81`, `ws/system.py:87`); frontend side `frontend/src/services/ws.ts:19`, `services/desktop-url.ts`. No auth token exists on these sockets (they rely on same-origin reachability), and a grep for Origin / TrustedHost / CORS in `backend/app` finds nothing.
- Scenario: the analyst has Tartarus open on a LAN or localhost address. Any web page they visit (including one served by malware infrastructure, or a link in a phishing sample's report) runs `new WebSocket('ws://tartarus-host/ws/analyses/12/desktop', 'guacamole')`. The browser sends no Origin restriction, so the page can watch the live guest screen and send keystrokes and mouse input into a running malware guest. Guest-controlled input is a detonation-control and information-disclosure issue, and a fast path to tampering with an analysis in progress. The live feed (`/live`) leaks events and process names the same way.
- Fix: in the WS handlers reject the handshake unless `Origin` host equals the `Host` header (or an allow-list setting), e.g. close with 1008 / HTTP 403 before `accept`. Add a test. Optionally also bind the stack to loopback or a management interface only.

### F2 - low - No CSP or other security response headers
- Where: `frontend/nginx.conf` (no `add_header` for security headers), `frontend/index.html` (no CSP meta).
- Scenario: nothing is exploitable today, but the app renders large volumes of attacker-controlled strings; a future `v-html` or a Quasar `html: true` toast would be an immediate stored XSS with no second line of defence. Also no clickjacking protection: a malicious page can frame Tartarus and drive the delete-analysis button or the desktop panel.
- Fix: add to the server block (note nginx `add_header` in a `location` replaces inherited ones, so repeat or use `include`):
  `Content-Security-Policy: default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'none'; object-src 'none'` plus `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. Quasar needs `'unsafe-inline'` for styles; check Material Icons font loads from `self` (the `extras` icons are bundled). Verify with `make screenshots` or a manual run.

### F3 - low - Screenshot, artifact and pcap responses carry no `X-Content-Type-Options: nosniff`
- Where: `backend/app/api/views_findings.py:108,127,140` (served by the same origin as the app). Frontend relies on the declared media type (`ScreenshotStrip.vue:45`, `ArtifactTable.vue:125`).
- Scenario: screenshots are produced by the guest and are guest-influenced bytes. They are served with a whitelist-derived `image/png` / `image/jpeg`, so risk is low, but without `nosniff` an older browser could sniff HTML if a malicious guest wrote an HTML-looking file with a `.png` extension and the response were navigated to directly (the lightbox opens it via `<img>`, which is not affected). Defence in depth only.
- Fix: global `nosniff` header (covered by F2's nginx change) and, for download endpoints, keep `Content-Disposition: attachment`.

### F4 - low - Route and download path segments built from data without `encodeURIComponent`
- Where: `frontend/src/components/guest/GuestCard.vue:243` (`/guest/clone/${guest.name}`), `GuestCard.vue:251` and `composables/use-guest-submission.ts:51` (the latter is encoded), `components/ArtifactTable.vue:17` (`artifact.id`). The other path-interpolated ids (`analysis_id`, `hit.analysis_id`, `verdict.analysisId`) are numeric.
- Scenario: guest names and artifact ids come from the server. If a guest name contained `/` or `?` (guest names are analyst-chosen, validated by the backend), the SPA link would resolve to a different route or query; for the artifact id (a hash-like server id) the download URL would point at another path on the same origin. No injection into HTML results. Not attacker-reachable from malware data as far as the code shows.
- Fix: wrap with `encodeURIComponent`, matching `desktop-url.ts` and `use-guest-submission.ts:51`.

### F5 - info - `laneMeta` / `LANE_STYLE` lookup with an unvalidated key
- Where: `frontend/src/services/lanes.ts:22,34` (`LANE_STYLE[lane]` on a plain object).
- Scenario: if an event ever carried a lane such as `constructor` or `toString` (not an allowed server enum value as far as seen), the lookup finds an `Object.prototype` member, `style.labelKey` is undefined and the badge renders `var(undefined)`. Cosmetic or a thrown error, no security impact; lane values are server-normalised.
- Fix: `Object.hasOwn(LANE_STYLE, lane)` instead of the truthy check.

### F6 - info - Rule `references` render as clickable external links
- Where: `frontend/src/components/DetectionDetail.vue:83-97`.
- Scenario: a Sigma rule from an untrusted pack can link to any http(s) URL. `rel="noopener noreferrer"` is set and `javascript:` is excluded, so only a phishing link is possible, and the rule source is analyst-supplied rather than malware. No fix needed; optionally show the host next to the link.

### Positives worth keeping (add or keep tests)
- No `v-html` anywhere; consider an ESLint rule (`vue/no-v-html: error`) so it stays that way.
- Guacamole `onclipboard`/`onfile`/`onpipe`/`onfilesystem` deliberately unset; a unit test asserting `DesktopSession` leaves them null would lock this in.
- `Notify.create` is never called with `html: true`; an ESLint `no-restricted-syntax` rule on the `html` key would lock this in.

## Severity-sorted table

| # | Sev | Area | File:line | Issue | Fix |
|---|---|---|---|---|---|
| F1 | medium | WebSocket | backend/app/ws/desktop.py:130 (also ws/live.py:81, ws/system.py:87) | No Origin check: any visited web page can open the guest desktop socket and watch/control the guest | Reject handshakes whose Origin host differs from Host |
| F2 | low | Build/headers | frontend/nginx.conf, frontend/index.html | No CSP, no frame-ancestors, no nosniff, no Referrer-Policy | Add CSP and security headers in nginx |
| F3 | low | Downloads | backend/app/api/views_findings.py:108,127,140 | Guest-produced screenshot/artifact responses lack nosniff | Global `X-Content-Type-Options: nosniff` |
| F4 | low | Links | GuestCard.vue:243; ArtifactTable.vue:17 | Path segments from server data not URI-encoded | `encodeURIComponent` |
| F5 | info | Rendering | services/lanes.ts:34 | Prototype-key lookup on `LANE_STYLE` | `Object.hasOwn` |
| F6 | info | Links | DetectionDetail.vue:88 | External rule reference links (guarded by https? regex, noopener) | None needed |
| - | none | XSS sinks, storage, PWA cache, sourcemaps, env vars, API client | - | Checked, nothing found | - |
