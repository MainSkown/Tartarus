# S0 findings: the i18n conventions

What was decided is in [gui.md, Internationalisation](../../specs/gui.md#internationalisation). This file is the evidence,
the rejected options and the pitfalls, for the tasks that migrate the other files.

## What was built

`vue-i18n` 11.4.16, `legacy: false`. `src/i18n/index.ts` (instance, typed `t`/`n`/`d`/`I18nT`), `src/i18n/en-US/`
(`guests`, `live`, `notes`, `formats`, `index`), `src/boot/i18n.ts`, `tests/setup/i18n.ts` (vitest `setupFiles`),
`framework.lang: 'en-US'` in `quasar.config.ts`. Migrated: `components/guest/GuestCard.vue`, `services/guest-build.ts`,
`composables/use-end-run.ts`, plus the number half of `services/format-number.ts` and `components/NoteEditor.vue`'s counter.

## Does `vue-tsc` reject a bad key? Not with vue-i18n's own types

Tried first: the documented way, `declare module 'vue-i18n' { interface DefineLocaleMessage extends MessageSchema {} }` plus
`createI18n<[MessageSchema], 'en-US'>`. It type-checks, autocompletes in the editor, and **accepts any string**: in v11 the
signature is `t<Key extends string>(key: Key | ResourceKeys | number)`, so `t('guests.card.nope')` and
`$t('guests.card.nope')` both compile. Same for `useI18n().t`, `n`, `d` and the `keypath` of `<i18n-t>`. The declaration
merging cannot be made strict, and `$t` cannot be re-declared (it is a `ComponentCustomProperties` member declared by
vue-i18n; declaring it again is TS2300, duplicate identifier, tried).

What works, and is in the tree:

- `MessageKey` = the dotted leaf paths of `typeof enUS` (a 6-line recursive mapped type). The catalogue object is the only
  list of keys; the type is derived from it, nothing is written twice.
- `t` is `i18n.global.t` re-typed to take `MessageKey` (four overloads: key, key+count, key+named, key+named+count).
  `n` takes a `NumberFormatKey` (`keyof` the formats object), `d` a `DatetimeFormatKey`.
- `I18nT` is vue-i18n's component re-typed so `keypath` is a `MessageKey`.
- Verified by writing bad keys: `t('guests.card.bad')` in a template, `t(\`guests.build.step.${s}\`)` where `s` includes a
  value with no key, `<I18nT keypath="guests.card.nope">` each gave a `vue-tsc` error. A `// @ts-expect-error` line in
  `tests/unit/i18n.test.ts` keeps that true (it fails `typecheck` if `t` ever turns loose again).
- **Consequence: nobody uses `$t` or `useI18n()`.** `$t('bad')` is the one spelling `vue-tsc` does not catch. I1 should add
  an ESLint `no-restricted-syntax` (or `no-restricted-imports` for `useI18n`) for them next to the vue-i18n lint rules;
  the key-usage unit test of I1 also catches a typo in a `$t` since the key would not be used.
- A template calls `t(...)` directly: `<script setup>` exposes the imported `t`. It is reactive to a future `locale` change
  because the global composer's `t` reads the locale ref during render.
- Cost: a synthetic 2,400-key catalogue (30 areas x 10 screens x 8 things) did not change `vue-tsc` time (about 7 s either
  way), so the union does not hit the instantiation depth limit at the size of this app (about 1,500 keys expected).

## Rejected

- **`$t` in templates, `useI18n()` in components.** Two spellings, loose types, and a component test would need the plugin.
  One imported `t` works everywhere (templates, services, composables, canvas).
- **JSON catalogues.** Would need `resolveJsonModule` types plus a separate schema file; a `.ts` object gives the
  type for free and allows a comment explaining a quirk.
- **One big `en-US.ts`.** About 1,500 keys and seven parallel agents: merge conflicts. One file per area.
- **Generated key constants (`KEYS.guests.card.default`).** A second list to keep in sync, and unreadable templates.
- **`unplugin-vue-i18n`** (precompiled messages, `<i18n>` blocks): another build plugin on the Quasar Vite config for no
  gain with one locale; the runtime compiler works (dev boot checked, no console warnings from `[intlify]`, no feature-flag
  warning, no CSP issue seen in dev). Revisit if bundle size matters.
- **`framework.lang` through a boot file.** `Quasar.lang.set(...)` in a boot file is for a runtime switcher; with one
  locale the config key is the whole job. When a second locale arrives, set both from one place.
- **A `d`-based UTC timestamp.** `Intl` cannot produce `YYYY-MM-DD HH:mm:ss UTC` from en-US options (it gives
  `10/16/2026, 09:30:00`), so `services/format-time.ts` stays hand-rolled and is not translated. No part of the app
  formats a date with `toLocaleDateString` today, so `datetimeFormats` is empty and `d` has no use yet (it is typed `never`
  until a format exists). **`d` was not run**; the rule (every named format sets `timeZone: 'UTC'`) is untested.
- **String-building plurals** (`'event' + (n === 1 ? '' : 's')`): kept out; see the plural rule below.

## Plurals, checked

`guest-build.ts` has no plural (the roadmap said it had); the plurals live in `guest-view.ts`, `rule-view.ts`,
`guest-media-view.ts`, `timeline-tooltip.ts`, `EventTable.vue`, `LiveEventStream.vue`, `DetectionList.vue`,
`ArtifactRegistry.vue`, `ScreenshotStrip.vue`, `ProcessViewSwitch.vue`, `RulesPage.vue`... (M1/M5/M7 find them by grepping
`=== 1 ?`). Proved in `tests/unit/i18n.test.ts` with a runtime-merged message `'{count} event | {count} events'`: 0 gives
`0 events`, 1 `1 event`, 2 `2 events`, i.e. the same as `count === 1 ? singular : plural`. With three forms vue-i18n picks
0 / 1 / 2+. `t(key, { count: n(total, 'count') }, total)` shows a grouped count (a named `count` overrides the implicit one).
A pluralised key that includes a noun taken from data (`{count} {lane} events`) is two messages' worth of grammar: keep the
data word as a named value.

## Pitfalls for the migrating agents

1. **Message syntax.** `@` throws (`a@b.c` is "Invalid linked format"), `|` silently splits into plural forms (a plain
   `t` returns only the first), `{x}` is interpolation (a literal `{here}` renders empty). Write `{'@'}`, `{'|'}`,
   `{'{'}`. `#`, `$`, `%`, `<`, `"` are fine. A message containing `<b>` logs an `[intlify] Detected HTML` warning.
2. **A missing named value renders as an empty string, with no error.** Every interpolated message needs a test that fills
   it (existing English assertions do, if they cover that path).
3. **Module-level constants.** The instance exists as soon as `@/i18n` is imported, so `const X = t('a.b')` would "work"
   today, but it freezes the locale for good and breaks the day a switcher exists. Store a `MessageKey` and call `t` when
   the text is read (`STEP_META` and `PHASE_META` in `guest-build.ts`), or make the constant a function
   (`cancelConfirmation` is now `cancelConfirmation()`: a call-site edit in `composables/use-guest-build.ts`, one line;
   callers of any other const that holds text change the same way). **Do this at the same time as the file** and grep the
   callers.
4. **`computed` vs plain value.** A `computed(() => t(...))` is right for text that depends on reactive state; a `t` inside
   a plain function called from the template re-runs every render and is fine too. Do not cache `t` results in a `ref`.
5. **Strings assembled from a prop noun.** `CopyButton` builds `` `${what} copied` `` and `` `Copy ${what}` `` from
   `what="password"`; `GuestCard` now passes `:what="t('guests.card.passwordNoun')"`. CopyButton itself is not migrated:
   its owner should make `copied`, `copyFailed` and `copy` three messages with a `{what}` value (English output unchanged).
   Look for the same shape in other shared components (`label`/`what`/`noun`/`unit` props).
6. **Data that looks like text.** `humanStepName('tamper-off')` uppercases the profile's own step name: data shown as
   received, not translated. The injected self-test step in `stepsWithSelfTest` is named `'self-test'` and shown through
   it as `SELF TEST`: an identifier formatted for display, left as is. Backend sentences matched on
   (`CANCELLED_BUILD_MESSAGE`) are never translated.
7. **Quasar props with strings** need the bound form: `label`, `placeholder`, `title`, `aria-label`, `hint`, `error-message`,
   `alt`, `caption` and the `label` of a `q-btn`/`q-tab`/`q-input`/`q-select` option become `:label="t('...')"`. Options
   arrays (`[{ label: 'X', value: 'x' }]`) hold keys or are built in a `computed` with `t`; the `value` is never translated.
   `Notify.create({ message })` and `Dialog.create({ title, message, ok: { label } })` take the translated string (done in
   `use-end-run.ts`, `services/confirm.ts` is M1's: its `'DELETE'` and `'CANCEL'` defaults).
8. **Uppercase.** Text such as `[RUN CHECKS]` is stored uppercase in the catalogue exactly as it was typed; a `text-transform`
   in CSS stays as it is. A string made uppercase by code (`humanStepName`, `kind.toUpperCase()`) operates on data and stays.
9. **Canvas text** (Timeline): `ctx.fillText(t('...'))` is fine; `t` runs at draw time. Measure after translating, and
   never cache measured widths across a locale change. Strings handed to `ctx.font` are CSS, not text.
10. **Test-only keys.** A test that needs a plural or a special message adds it with `i18n.global.mergeLocaleMessage` and
    reads it with `t(key as MessageKey)`, as `i18n.test.ts` does. I1's "every catalogue key is used" check then ignores it
    (it is not in the files).
11. **`<i18n-t>` and the parent scope.** Without `scope="global"` it logs `[intlify] Not found parent scope` on every mount.
12. **A mount that passes the plugin itself** (`global.plugins: [i18n]`) installs it twice; Vue skips an already installed
    plugin (tried: the test passes, no warning printed), but it is noise, do not. A mount with `[Quasar, router]` is fine (proved).
13. **`exactOptionalPropertyTypes`** is off project-wide (see `quasar.config.ts`), so `{ confirmLabel: t(...) }` needs no
    spread tricks.
14. **Pre-existing, not ours:** `npm run typecheck` reports one error in `tests/screenshots/header-health-dots.spec.ts` (an
    untouched file, `{}` passed where `getBody` is required), and the screenshot harness is not deterministic (see the
    plan's Status).
15. **Files this spike did not migrate but touched**: `use-guest-build.ts` (one line, `cancelConfirmation()`); `services/end-run.ts`
    (`endRunLabel`, `endRunTitle`; M1), `services/confirm.ts` (M1), `services/guest-view.ts` (`GIVEAWAY_ADVICE`, M1) still hold
    English the migrated files use. `GuestCard`'s `systemLabel`, `resourcesLabel` and `selfTestOf().message` come from services.

## Migration recipe (copy it)

**A template file** (`*.vue`)
1. Read the file; list every user-readable string: text nodes, `label`, `placeholder`, `title`, `aria-label`, `hint`,
   `alt`, `caption`, strings in `<script>` (toasts, option labels, error text built in code).
2. Skip what must not be translated (gui.md list). Check the existing test for the English text it asserts.
3. Add the keys to `src/i18n/en-US/<your area>.ts`, `area.screen.thing`, text copied character for character.
   One sentence = one message; `{name}` for values; `a | b` for plurals; `{'@'}` for `@`, `|`, braces.
4. In `<script setup>`: `import { t } from '@/i18n'`. Replace each text node with `{{ t('...') }}`, each attribute with
   `:attr="t('...')"`, with the values passed as `{ name: value }`.
5. Run the file's test, then `npm run typecheck` (a wrong key fails here), then `npm run lint`.

**A service** (`services/*.ts`)
1. Write or extend the test first if the output changes shape (a const turning into a function, a split message). Otherwise
   the existing test is the guard.
2. Messages go in the area file. `import { t, type MessageKey } from '@/i18n'`.
3. A table holding text keeps `MessageKey`s (`Record<Status, MessageKey>`); the function that returns the text calls `t`.
4. A const object holding text becomes a function; grep and update the callers (list them in your report).
5. Leave API-sent strings, ids, and the CSS and icon names in the tables alone.

**A composable** (`composables/use-*.ts`)
1. Same as a service. Toasts: `Notify.create({ type, message: t('...') })`; confirms: pass `t(...)` for each of
   `title`, `message`, `confirmLabel`. `t` is called when the action runs, never at the top of the file.
2. A message built from a backend error stays the backend's text (`errorMessage(error)`); only our own sentences move.
3. Test: the existing assertions on `Notify.create` / the confirm options still hold with the English text.

## Visual check

Specs run: `guest-page`, `guest-build`, `guest-build-cancel`, `guest-choice`, `live` (end-run), `notes`: 151 specs pass.
Compared against the B0 baselines (`compare_shots.py` plus a second after-run, because the single-box noise model flagged 50
images that differ only by animated dots and spinners in places the baseline runs did not happen to catch): 72 images
identical, 73 differ only in animation noise, 1 flagged and looked at by eye (`live-end-run-not-started.png`, the running
process rows: text and layout identical, the pulse markers differ). No text or layout change anywhere.
