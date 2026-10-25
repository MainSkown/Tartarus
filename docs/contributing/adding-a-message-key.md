# Adding a message key

Every string the user reads comes from the English catalogue. Only `en-US` ships in v1, with no
language switcher, so adding a language later is out of scope here. The full rules are in the
[GUI spec, Internationalisation](../specs/gui.md#internationalisation). This page is the working order.

## Where a key goes

- The catalogue is `frontend/src/i18n/en-US/`, one file per area: `analysis.ts`, `guests.ts`,
  `iocs.ts`, and so on. Each file default-exports a nested object. `en-US/index.ts` composes them,
  and the file name is the top-level key.
- Add the key to the file of its own area. Name the thing, not the English text, in camelCase, as
  `area.screen.thing`, for example `analysis.warnings.label`.
- `common.ts` holds the generic words (CLOSE, CANCEL). Do not share a key across areas.
- Write the text exactly as it should show, upper case included. Do not rely on `text-transform`.

## Use it

Import `t` from `@/i18n`. Never use `$t` or `useI18n`: the lint rules reject them outside `src/i18n/`
and `src/boot/`. The same import works in `<script setup>`, in templates, in services and in composables.

```vue
<!-- AnalysisWarnings.vue -->
<div :aria-label="t('analysis.warnings.label')">
```

Rules that the tests and the lint do not enforce:

- Never call `t` at module top level, and never keep translated text in a module-level constant. A
  constant holds a `MessageKey`, or becomes a function, so `t` runs where the text is read.
- Do not build a sentence from pieces. Put the whole sentence in one message, so the translator
  controls word order.

## Interpolation and plurals

A named value uses `{name}`: `t('guests.build.failure.step', { step: 'TAMPER OFF' })` gives
`TAMPER OFF FAILED`. A missing named value renders empty and raises no error, so test each
interpolated message.

Forms are separated by `|`. English has two: `'{count} event | {count} events'`, called as `t(key, count)`.
A count shown with grouping is passed formatted, with the raw number as the plural count:

```ts
t('iocs.analyses.eventCount', { count: formatCount(hit.count) }, hit.count)
```

Every number followed by a noun is a plural message, with the whole sentence in each form, even when
the number is a constant. Do not write `'{n} events'`, because a count can be 1.

## Markup in a message

Put links and bold parts in the message with component interpolation, not HTML:

```vue
<I18nT keypath="events.query.useSuggestion" scope="global" tag="span">
  <template #suggestion><strong>{{ firstError.suggestion }}</strong></template>
</I18nT>
```

Here the message is `'use {suggestion}'` in `frontend/src/i18n/en-US/events.ts`, and the slot fills the
placeholder with markup. See `frontend/src/components/QueryBar.vue`.

`I18nT` comes from `@/i18n`, and `scope="global"` is always passed. Never use `v-html`; the lint rule
`vue/no-v-html` rejects it. In a message, `@`, `|`, `{` and `}` are syntax, so write them as literal
interpolations: `{'@'}`, `{'|'}`.

## The typed schema

`MessageKey` in `frontend/src/i18n/index.ts` is the union of every dotted leaf path of the en-US
object. `t` accepts only a `MessageKey`, so a key that is not in the catalogue is a type error. Run
`cd frontend && npm run typecheck`. Template-literal keys such as ``t(`guests.build.step.${status}`)``
are checked against every value of `status`.

## The unused-key test

`frontend/tests/unit/i18n-keys.test.ts` checks both directions:

- A key used in `src/` (a literal `t('...')`, a `keypath`, or a template key that matches a leaf)
  that is not in the catalogue fails the test.
- A catalogue key that nothing in `src/` mentions fails the test. The scanner looks for the key as a
  quoted string anywhere in `src/`, so write the key as a literal, never assemble it at run time.

Add the key and the code that uses it in the same change. Run it with
`cd frontend && npm run test:unit -- tests/unit/i18n-keys.test.ts`.

## The lint rules

`npm run lint` uses `frontend/eslint.i18n-rules.js`, which sets these rules:

- `@intlify/vue-i18n/no-raw-text` rejects raw text in `src/**/*.vue`. Punctuation, symbols, numbers and
  spaces alone pass.
- The text-bearing attributes (`label`, `title`, `placeholder`, `aria-label`, `hint`, `message` and
  others) must not hold a literal with letters, whether bound or not.
- `$t` and `useI18n` are rejected, and `useI18n` cannot be imported from `vue-i18n`.

Raw strings in `.ts` files and in `<script>` blocks are not caught by tooling, so review them. The
[GUI spec](../specs/gui.md#internationalisation) lists what is not translated: API messages shown as
received, identifiers, query-grammar tokens, log text and console messages.

## Tests

`frontend/tests/unit/i18n.test.ts` shows the plural and interpolation pattern. The vitest setup
(`frontend/tests/setup/i18n.ts`) installs the plugin for every `@vue/test-utils` mount, so a test
needs nothing extra. Keep assertions on the English text.
