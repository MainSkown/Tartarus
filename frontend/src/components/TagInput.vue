<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch, type CSSProperties } from 'vue'
import { Notify } from 'quasar'
import TagChip from '@/components/TagChip.vue'
import { t } from '@/i18n'
import { checkTagName } from '@/services/tag-name'
import { useAnnotationsStore, type AnnotationTarget } from '@/stores/annotations'
import { useTagsStore } from '@/stores/tags'

/**
 * The tags of one target (the analysis, a process or an event) as removable chips, and a plus
 * button that opens an input: Enter adds what is typed or highlighted, the list under it suggests
 * the tags already in use. What is wrong with a name shows beside the input, never as a toast.
 */
const props = withDefaults(defineProps<{ target: AnnotationTarget; editable?: boolean }>(), { editable: true })

const annotations = useAnnotationsStore()
const knownTags = useTagsStore()
const listId = useId()

const open = ref(false)
const typed = ref('')
const refusal = ref<string>()
const adding = ref(false)
const highlighted = ref(-1)
const field = ref<HTMLInputElement>()
const popoverStyle = ref<CSSProperties>({})

const links = computed(() => annotations.tagsOf(props.target))
const names = computed(() => links.value.map((link) => link.tag))
const check = computed(() => checkTagName(typed.value))
const problem = computed(() => {
  if ('name' in check.value) return names.value.includes(check.value.name) ? t('tags.input.duplicate') : undefined
  return check.value.problem ?? undefined
})
const message = computed(() => refusal.value ?? problem.value)
const suggestions = computed(() => knownTags.suggest(typed.value, names.value))
const activeOption = computed(() => (highlighted.value >= 0 ? `${listId}-${highlighted.value}` : undefined))

const POPOVER_GAP_PX = 2
const POPOVER_MAX_HEIGHT_PX = 224
const POPOVER_MIN_HEIGHT_PX = 96
const WINDOW_MARGIN_PX = 16

// Fixed, under the input's box: a popover inside the scrolling drawer or process panel would be cut off by it.
function placePopover(): void {
  const box = field.value?.getBoundingClientRect()
  if (!box) return
  const room = window.innerHeight - box.bottom - WINDOW_MARGIN_PX
  popoverStyle.value = {
    top: `${box.bottom + POPOVER_GAP_PX}px`,
    left: `${box.left}px`,
    width: `${box.width}px`,
    '--popover-max-height': `${Math.max(POPOVER_MIN_HEIGHT_PX, Math.min(POPOVER_MAX_HEIGHT_PX, room))}px`,
  }
}

const showPopover = computed(() => open.value && (message.value !== undefined || suggestions.value.length > 0))

watch(showPopover, (shown) => {
  if (shown) void nextTick(placePopover)
})
onMounted(() => {
  window.addEventListener('scroll', placePopover, true)
  window.addEventListener('resize', placePopover)
})
onBeforeUnmount(() => {
  window.removeEventListener('scroll', placePopover, true)
  window.removeEventListener('resize', placePopover)
})

async function openField(): Promise<void> {
  open.value = true
  void knownTags.load()
  await nextTick()
  field.value?.focus()
}

function closeField(): void {
  open.value = false
  typed.value = ''
  refusal.value = undefined
  highlighted.value = -1
}

function onInput(): void {
  refusal.value = undefined
  highlighted.value = -1
}

async function add(name: string): Promise<void> {
  if (adding.value) return
  adding.value = true
  refusal.value = await annotations.addTag(props.target, name)
  adding.value = false
  if (refusal.value === undefined) typed.value = ''
  highlighted.value = -1
  field.value?.focus()
}

async function submit(): Promise<void> {
  const picked = suggestions.value[highlighted.value]
  if (picked) return add(picked.name)
  if ('name' in check.value && problem.value === undefined) await add(check.value.name)
}

function moveHighlight(step: 1 | -1): void {
  const count = suggestions.value.length
  if (count === 0) return
  const next = highlighted.value + step
  highlighted.value = next < 0 ? count - 1 : next % count
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter') void submit()
  else if (event.key === 'Escape') closeField()
  else if (event.key === 'ArrowDown') moveHighlight(1)
  else if (event.key === 'ArrowUp') moveHighlight(-1)
  else return
  event.preventDefault()
}

function onBlur(): void {
  if (typed.value === '') closeField()
}

async function remove(linkId: number): Promise<void> {
  if (!(await annotations.removeTag(linkId))) Notify.create({ type: 'tt-error', message: t('tags.input.removeFailed') })
}
</script>

<template>
  <div class="tag-input">
    <ul
      class="tag-input__chips"
      :aria-label="t('tags.list.label')"
    >
      <li
        v-for="link in links"
        :key="link.link_id"
      >
        <TagChip
          :name="link.tag"
          :removable="editable"
          @remove="remove(link.link_id)"
        />
      </li>
      <li v-if="editable && !open">
        <button
          type="button"
          class="tag-input__add text-mono"
          :aria-label="t('tags.input.add')"
          @click="openField"
        >
          <q-icon
            name="add"
            size="16px"
            aria-hidden="true"
          />
        </button>
      </li>
      <li
        v-if="open"
        class="tag-input__entry"
      >
        <input
          ref="field"
          v-model="typed"
          type="text"
          class="input-field tag-input__field text-mono"
          :class="{ 'is-invalid': message !== undefined }"
          role="combobox"
          :aria-label="t('tags.input.label')"
          aria-autocomplete="list"
          :aria-expanded="suggestions.length > 0"
          :aria-controls="listId"
          :aria-activedescendant="activeOption"
          :aria-describedby="message ? `${listId}-message` : undefined"
          :placeholder="t('tags.input.placeholder')"
          autocomplete="off"
          spellcheck="false"
          @input="onInput"
          @keydown="onKeydown"
          @blur="onBlur"
        >
        <Teleport to="body">
          <div
            v-if="showPopover"
            class="tag-input__popover"
            :style="popoverStyle"
          >
            <p
              v-if="message"
              :id="`${listId}-message`"
              class="tag-input__message text-mono"
              role="alert"
            >
              {{ message }}
            </p>
            <ul
              v-if="suggestions.length > 0"
              :id="listId"
              class="tag-input__options"
              role="listbox"
              :aria-label="t('tags.input.suggestions')"
            >
              <li
                v-for="(option, index) in suggestions"
                :id="`${listId}-${index}`"
                :key="option.name"
                class="tag-input__option text-mono"
                :class="{ 'is-highlighted': index === highlighted }"
                role="option"
                :aria-selected="index === highlighted"
                @mousedown.prevent="add(option.name)"
              >
                <span class="tag-input__option-name">{{ option.name }}</span>
                <span class="tag-input__option-count text-gray">{{ option.count }}</span>
              </li>
            </ul>
          </div>
        </Teleport>
      </li>
      <li
        v-if="links.length === 0 && !editable"
        class="tag-input__none text-mono text-gray"
      >
        {{ t('tags.input.none') }}
      </li>
    </ul>
  </div>
</template>

<style scoped>
.tag-input {
  min-width: 0;
  max-width: 100%;
}

.tag-input__chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-xs);
  margin: 0;
  padding: 0;
  list-style: none;
}

.tag-input__chips > li {
  display: flex;
  min-width: 0;
  max-width: 100%;
}

.tag-input__none {
  font-size: 0.75rem;
}

.tag-input__add {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 1px dashed var(--border-secondary);
  background: transparent;
  color: var(--text-gray);
  cursor: pointer;
}

.tag-input__add:hover,
.tag-input__add:focus-visible {
  border-color: var(--blue-primary);
  color: var(--blue-hover);
}

/* The input takes the plus button's place in the row, so opening it moves nothing around it. */
.tag-input__chips > .tag-input__entry {
  position: relative;
  width: 14rem;
}

.tag-input__field {
  width: 100%;
  height: 24px;
  padding: 0 var(--spacing-sm);
  font-size: 0.75rem;
}

.tag-input__popover {
  position: fixed;
  /* Above Quasar's dialogs (z-index 6000), which hold the event drawer. */
  z-index: 7000;
  border: 1px solid var(--border-secondary);
  background: var(--card-bg);
}

.tag-input__message {
  margin: 0;
  padding: var(--spacing-xs) var(--spacing-sm);
  color: var(--status-critical);
  font-size: 0.7rem;
  overflow-wrap: anywhere;
}

.tag-input__options {
  max-height: var(--popover-max-height, 14rem);
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.tag-input__message + .tag-input__options {
  border-top: 1px solid var(--border-subtle);
}

.tag-input__option {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--spacing-sm);
  padding: var(--spacing-xs) var(--spacing-sm);
  font-size: 0.8rem;
  cursor: pointer;
}

.tag-input__option-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-input__option-count {
  flex: none;
  font-size: 0.7rem;
}

.tag-input__option:hover,
.tag-input__option.is-highlighted {
  background: var(--hover-bg);
  color: var(--blue-hover);
}
</style>
