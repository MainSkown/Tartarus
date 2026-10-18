<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import QueryCheatSheet from '@/components/QueryCheatSheet.vue'
import { useQuerySuggestions, type SuggestionItem } from '@/composables/use-query-suggestions'
import { useQueryValidation } from '@/composables/use-query-validation'
import { applySuggestion } from '@/services/query-token'
import { applyErrorSuggestion, underlineSegments } from '@/services/query-underline'
import type { QueryErrorRead } from '@/api'
import { I18nT, t } from '@/i18n'
import { useQueryStateStore } from '@/stores/query-state'

const props = defineProps<{ analysisId: number }>()

const store = useQueryStateStore()
const uid = useId()
const listId = `${uid}-suggestions`
const optionId = (index: number): string => `${uid}-option-${index}`

// The draft is the one place the bar's text lives before it is applied; the applied text is the store's.
const draft = ref(store.text)
const caret = ref(draft.value.length)
const scrollLeft = ref(0)
const input = ref<HTMLInputElement>()
const mirror = ref<HTMLElement>()
const cheatSheetOpen = ref(false)

const suggestions = useQuerySuggestions(draft, caret, () => props.analysisId)
const validation = useQueryValidation(draft)

const errors = computed(() => [...validation.errors.value].sort((a, b) => a.start - b.start))
const firstError = computed(() => errors.value[0])
const segments = computed(() => underlineSegments(draft.value, errors.value))
const canClear = computed(() => draft.value !== '' || store.text !== '')

interface HoveredError {
  error: QueryErrorRead
  left: number
}
const hovered = ref<HoveredError>()
const root = ref<HTMLElement>()

function syncFromInput(): void {
  caret.value = input.value?.selectionStart ?? draft.value.length
  scrollLeft.value = input.value?.scrollLeft ?? 0
}

function onInput(event: Event): void {
  draft.value = (event.target as HTMLInputElement).value
  hovered.value = undefined
  suggestions.reveal()
  syncFromInput()
}

async function placeCaret(position: number): Promise<void> {
  caret.value = position
  await nextTick()
  input.value?.focus()
  input.value?.setSelectionRange(position, position)
  syncFromInput()
}

async function accept(item: SuggestionItem): Promise<void> {
  const next = applySuggestion(draft.value, suggestions.token.value, suggestions.suggestionFor(item))
  draft.value = next.text
  if (item.kind === 'value') suggestions.dismiss()
  else suggestions.reveal()
  await placeCaret(next.caret)
}

async function apply(): Promise<void> {
  suggestions.dismiss()
  const found = await validation.settle()
  if (found.length > 0) return
  const text = draft.value.trim()
  draft.value = text
  store.setText(text)
}

function clear(): void {
  draft.value = ''
  store.setText('')
  suggestions.dismiss()
  void placeCaret(0)
}

function useErrorSuggestion(error: QueryErrorRead): void {
  draft.value = applyErrorSuggestion(draft.value, error)
  void placeCaret(draft.value.length)
}

function useExample(query: string): void {
  draft.value = query
  suggestions.dismiss()
  void placeCaret(query.length)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.isComposing) return
  if (suggestions.open.value && handleListKey(event)) return
  if (event.key === 'ArrowDown') suggestions.reveal()
  if (event.key === 'Enter') {
    event.preventDefault()
    void apply()
  }
}

/** Keys that act on the open list; true when one did, so the key does nothing else. */
function handleListKey(event: KeyboardEvent): boolean {
  const chosen = suggestions.active.value ?? (event.key === 'Tab' ? suggestions.items.value[0] : undefined)
  switch (event.key) {
    case 'ArrowDown':
    case 'ArrowUp':
      event.preventDefault()
      suggestions.move(event.key === 'ArrowDown' ? 1 : -1)
      return true
    case 'Escape':
      event.preventDefault()
      suggestions.dismiss()
      return true
    case 'Tab':
    case 'Enter':
      if (!chosen) return false
      event.preventDefault()
      void accept(chosen)
      return true
    default:
      return false
  }
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const editable = ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable
  return editable || target.closest('[role="dialog"]') !== null
}

function focusOnSlash(event: KeyboardEvent): void {
  const plain = !event.ctrlKey && !event.metaKey && !event.altKey
  if (event.key !== '/' || !plain || isTypingTarget(event.target)) return
  event.preventDefault()
  input.value?.focus()
}

function contains(rect: DOMRect, x: number, y: number): boolean {
  return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom
}

/** The mirror cannot take the pointer (it sits over the input), so the underlined span is found by its box. */
function onMouseMove(event: MouseEvent): void {
  const spans = mirror.value?.querySelectorAll<HTMLElement>('[data-segment]') ?? []
  const hit = [...spans].find((span) => [...span.getClientRects()].some((rect) => contains(rect, event.clientX, event.clientY)))
  const error = hit ? segments.value[Number(hit.dataset.segment)]?.error : undefined
  const origin = root.value?.getBoundingClientRect().left ?? 0
  hovered.value = hit && error ? { error, left: Math.max(0, hit.getBoundingClientRect().left - origin) } : undefined
}

watch(
  () => store.text,
  (applied) => {
    if (applied !== draft.value.trim()) draft.value = applied
  },
)

onMounted(() => document.addEventListener('keydown', focusOnSlash))
onBeforeUnmount(() => document.removeEventListener('keydown', focusOnSlash))
</script>

<template>
  <div
    ref="root"
    class="query-bar"
  >
    <div class="terminal-input-group query-bar__group">
      <div
        ref="mirror"
        class="query-bar__mirror text-mono"
        aria-hidden="true"
      >
        <div class="query-bar__clip">
          <div
            class="query-bar__text"
            :style="{ transform: `translateX(${-scrollLeft}px)` }"
          >
            <span
              v-for="(segment, index) in segments"
              :key="index"
              :class="{ 'query-bar__error': segment.error }"
              :data-segment="segment.error ? index : undefined"
            >{{ segment.text }}</span>
          </div>
        </div>
      </div>

      <input
        ref="input"
        class="input-field query-bar__input text-mono"
        :class="{ 'is-invalid': firstError }"
        type="text"
        role="combobox"
        :aria-label="t('events.query.label')"
        aria-autocomplete="list"
        :aria-expanded="suggestions.open.value"
        :aria-controls="listId"
        :aria-activedescendant="suggestions.active.value ? optionId(suggestions.activeIndex.value) : undefined"
        :aria-invalid="firstError ? 'true' : undefined"
        :placeholder="t('events.query.placeholder')"
        spellcheck="false"
        autocomplete="off"
        autocapitalize="off"
        :value="draft"
        @input="onInput"
        @keydown="onKeydown"
        @keyup="syncFromInput"
        @click="syncFromInput"
        @select="syncFromInput"
        @scroll="syncFromInput"
        @focus="syncFromInput"
        @blur="suggestions.dismiss()"
        @mousemove="onMouseMove"
        @mouseleave="hovered = undefined"
      >

      <div class="query-bar__buttons">
        <button
          v-if="canClear"
          type="button"
          class="query-bar__button text-mono"
          :aria-label="t('events.query.clear')"
          :title="t('events.query.clear')"
          @click="clear"
        >
          ✕
        </button>
        <button
          type="button"
          class="query-bar__button text-mono"
          :aria-label="t('events.query.syntaxHelp')"
          :title="t('events.query.syntaxTitle')"
          @click="cheatSheetOpen = true"
        >
          ?
        </button>
      </div>

      <div
        v-if="hovered && !suggestions.open.value"
        class="query-bar__tooltip"
        role="tooltip"
        :style="{ left: `${hovered.left}px` }"
      >
        {{ hovered.error.message }}
      </div>
    </div>

    <ul
      v-if="suggestions.open.value"
      :id="listId"
      class="query-bar__suggestions scrollable-panel"
      role="listbox"
      :aria-label="t('events.query.suggestions')"
    >
      <li
        v-for="(item, index) in suggestions.items.value"
        :id="optionId(index)"
        :key="item.kind === 'field' ? item.field.name : item.value"
        class="query-bar__option text-mono"
        :class="{ 'is-active': index === suggestions.activeIndex.value, 'query-bar__option--value': item.kind === 'value' }"
        role="option"
        :aria-selected="index === suggestions.activeIndex.value"
        :title="item.kind === 'field' ? item.field.description : undefined"
        @mousedown.prevent="accept(item)"
      >
        <template v-if="item.kind === 'field'">
          <span class="query-bar__option-name">{{ item.field.name }}</span>
          <span class="query-bar__option-type">{{ item.field.type }}</span>
          <span
            v-if="item.field.aliases.length > 0"
            class="query-bar__option-aliases"
          >{{ item.field.aliases.join(', ') }}</span>
          <span
            v-if="item.field.example"
            class="query-bar__option-example"
          >{{ item.field.example }}</span>
        </template>
        <template v-else>
          <span class="query-bar__option-name">{{ item.value }}</span>
          <span class="query-bar__option-count">{{ item.count }}</span>
        </template>
      </li>
    </ul>

    <p
      v-if="firstError"
      class="query-bar__message text-mono"
      aria-live="polite"
    >
      <span class="query-bar__message-text">{{ firstError.message }}</span>
      <span v-if="errors.length > 1">{{ t('events.query.moreErrors', { count: errors.length - 1 }) }}</span>
      <button
        v-if="firstError.suggestion"
        type="button"
        class="query-bar__suggestion"
        @click="useErrorSuggestion(firstError)"
      >
        <I18nT
          keypath="events.query.useSuggestion"
          scope="global"
          tag="span"
        >
          <template #suggestion>
            <strong>{{ firstError.suggestion }}</strong>
          </template>
        </I18nT>
      </button>
    </p>

    <QueryCheatSheet
      v-model="cheatSheetOpen"
      @choose="useExample"
    />
  </div>
</template>

<style scoped>
.query-bar {
  position: relative;
  min-width: 0;
}

.query-bar__group {
  position: relative;
  /* One font and one set of paddings for the input and its mirror: the underline only lines up while they match. */
  --bar-font-size: 0.95rem;
  --bar-line-height: 1.5rem;
  --bar-padding-left: calc(var(--spacing-md) + 1.25rem);
  --bar-padding-right: 5rem;
}

.query-bar__input {
  width: 100%;
  height: 2.75rem;
  padding-right: var(--bar-padding-right);
  font-family: var(--font-mono);
  font-size: var(--bar-font-size);
  line-height: var(--bar-line-height);
}

.query-bar__input::placeholder {
  font-family: var(--font-mono);
}

/* An error is a threat signal, not decoration, but a dark red field behind the underline would hide it. */
.query-bar__input.is-invalid,
.query-bar__input.is-invalid:focus {
  background-color: var(--black) !important;
  border-color: var(--status-critical) !important;
}

.query-bar__mirror {
  position: absolute;
  z-index: 1;
  inset: 0;
  box-sizing: border-box;
  padding: var(--spacing-sm) var(--bar-padding-right) var(--spacing-sm) var(--bar-padding-left);
  border: 2px solid transparent;
  color: transparent;
  font-size: var(--bar-font-size);
  line-height: var(--bar-line-height);
  pointer-events: none;
}

.query-bar__clip {
  /* Taller than the text line so the wavy underline, drawn below the line, is not cut off. */
  height: calc(var(--bar-line-height) + var(--spacing-sm));
  overflow: hidden;
}

.query-bar__text {
  width: max-content;
  white-space: pre;
}

.query-bar__error {
  text-decoration: underline wavy var(--status-critical);
  text-decoration-thickness: 1.5px;
  text-underline-offset: 4px;
}

.query-bar__buttons {
  position: absolute;
  z-index: 2;
  top: 50%;
  right: var(--spacing-sm);
  display: flex;
  gap: var(--spacing-xs);
  transform: translateY(-50%);
}

.query-bar__button {
  min-width: 1.75rem;
  height: 1.75rem;
  padding: 0 var(--spacing-xs);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-gray);
  font-size: 0.85rem;
  cursor: pointer;
  transition: color var(--transition-fast), background-color var(--transition-fast), border-color var(--transition-fast);
}

.query-bar__button:hover,
.query-bar__button:focus-visible {
  border-color: var(--border-primary);
  background: var(--hover-bg);
  color: var(--blue-hover);
  outline: none;
}

.query-bar__tooltip {
  position: absolute;
  z-index: 4;
  bottom: calc(100% + var(--spacing-xs));
  max-width: min(32rem, 100%);
  padding: var(--spacing-xs) var(--spacing-sm);
  border: 1px solid var(--blue-primary);
  background: var(--card-bg);
  color: var(--text-white);
  font-size: 0.8rem;
  pointer-events: none;
}

.query-bar__suggestions {
  position: absolute;
  z-index: 3;
  top: calc(2.75rem + 2px);
  right: 0;
  left: 0;
  max-height: 16rem;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  border: 1px solid var(--border-secondary);
  background: var(--card-bg);
  list-style: none;
}

.query-bar__option {
  display: grid;
  grid-template-columns: minmax(0, 27ch) 17ch minmax(0, 1fr) minmax(0, auto);
  align-items: baseline;
  gap: var(--spacing-md);
  padding: var(--spacing-xs) var(--spacing-md);
  font-size: 0.8rem;
  cursor: pointer;
}

.query-bar__option--value {
  grid-template-columns: minmax(0, 1fr) auto;
}

.query-bar__option--value .query-bar__option-count {
  grid-column: auto;
}

.query-bar__option:hover,
.query-bar__option.is-active {
  background: var(--hover-bg);
}

.query-bar__option.is-active {
  box-shadow: inset 2px 0 0 var(--blue-primary);
}

.query-bar__option-name {
  overflow: hidden;
  color: var(--text-white);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.query-bar__option-type {
  justify-self: start;
  padding: 0 var(--spacing-xs);
  border: 1px solid var(--border-primary);
  color: var(--blue-light);
  font-size: 0.7rem;
}

.query-bar__option-aliases {
  min-width: 0;
  overflow: hidden;
  color: var(--text-gray);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.query-bar__option-example,
.query-bar__option-count {
  min-width: 0;
  grid-column: 4;
  justify-self: end;
  overflow: hidden;
  color: var(--text-gray-dark);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.query-bar__message {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--spacing-sm);
  margin: var(--spacing-xs) 0 0;
  color: var(--status-critical);
  font-size: 0.75rem;
}

.query-bar__message-text {
  min-width: 0;
  overflow-wrap: anywhere;
}

.query-bar__suggestion {
  padding: 0 var(--spacing-sm);
  border: 1px solid var(--border-primary);
  background: transparent;
  color: var(--blue-light);
  font: inherit;
  cursor: pointer;
}

.query-bar__suggestion:hover,
.query-bar__suggestion:focus-visible {
  background: var(--hover-bg);
  color: var(--blue-hover);
  outline: none;
}
</style>
