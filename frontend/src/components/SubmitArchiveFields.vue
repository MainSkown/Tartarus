<script setup lang="ts">
import { computed, watch } from 'vue'
import type { ArchiveMemberRead } from '@/api'
import { t } from '@/i18n'
import { hasEncryptedMember, isSelectableMember } from '@/services/archive-file'
import { formatFileSize } from '@/services/file-size'

const props = withDefaults(
  defineProps<{
    members: ArchiveMemberRead[]
    loading: boolean
    passwordOk?: boolean | null
    passwordError?: string
    entryError?: string
    disable?: boolean
  }>(),
  { passwordOk: undefined, passwordError: undefined, entryError: undefined, disable: false },
)
const password = defineModel<string>('password', { required: true })
const entry = defineModel<string>('entry', { required: true })

const passwordOptional = computed(() => props.members.length > 0 && !hasEncryptedMember(props.members))
const verdictShown = computed(() => props.passwordOk === false && !props.loading)
const passwordMessage = computed(
  () => props.passwordError ?? (verdictShown.value ? t('submit.archive.password.wrong') : undefined),
)
const firstListing = computed(() => props.loading && props.members.length === 0)
const noFiles = computed(() => !props.loading && props.members.length === 0)

function reasonOf(member: ArchiveMemberRead): { label: string; hint: string } | undefined {
  if (member.unsafe) return { label: t('submit.archive.entry.unsafe'), hint: t('submit.archive.entry.unsafeHint') }
  if (member.unsupported) {
    return { label: t('submit.archive.entry.unsupported'), hint: t('submit.archive.entry.unsupportedHint') }
  }
  return undefined
}

watch(
  () => props.members,
  (members) => {
    const selectable = members.filter(isSelectableMember)
    if (selectable.some((member) => member.name === entry.value)) return
    const onlyChoice = selectable.length === 1 ? selectable[0]!.name : ''
    if (entry.value !== onlyChoice) entry.value = onlyChoice
  },
  { immediate: true },
)
</script>

<template>
  <div class="archive-fields">
    <q-input
      v-model="password"
      :label="passwordOptional ? t('submit.archive.password.optionalLabel') : t('submit.archive.password.label')"
      outlined
      dense
      hide-bottom-space
      :disable="disable"
      :error="Boolean(passwordMessage)"
      :error-message="passwordMessage"
      class="archive-password text-mono"
    />

    <div class="archive-entry">
      <span class="archive-entry-title field-title text-mono">{{ t('submit.archive.entry.title') }}</span>
      <p
        v-if="firstListing"
        class="archive-loading text-gray"
        role="status"
      >
        {{ t('submit.archive.entry.loading') }}
      </p>
      <p
        v-else-if="noFiles"
        class="archive-empty text-gray"
      >
        {{ t('submit.archive.entry.empty') }}
      </p>
      <div
        v-else
        class="member-list"
        role="radiogroup"
        :aria-label="t('submit.archive.entry.group')"
        :aria-busy="loading"
      >
        <label
          v-for="member in members"
          :key="member.name"
          class="member-row"
          :class="{
            'member-row--selected': entry === member.name,
            'member-row--refused': !isSelectableMember(member),
          }"
        >
          <input
            type="radio"
            name="archive-entry"
            class="member-radio"
            :value="member.name"
            :checked="entry === member.name"
            :disabled="disable || !isSelectableMember(member)"
            @change="entry = member.name"
          >
          <span
            class="member-name text-mono"
            :title="member.name"
          >{{ member.name }}</span>
          <span class="member-size text-mono text-gray">{{ formatFileSize(member.size) }}</span>
          <span
            v-if="reasonOf(member)"
            class="member-reason text-mono"
            :title="reasonOf(member)?.hint"
          >{{ reasonOf(member)?.label }}</span>
        </label>
      </div>
      <p
        v-if="entryError"
        class="field-error archive-entry-error"
        role="alert"
      >
        {{ entryError }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.archive-fields {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
  min-width: 0;
}

.archive-entry {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  min-width: 0;
}

.field-title {
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.archive-loading,
.archive-empty {
  margin: 0;
  font-size: 0.75rem;
}

.member-list {
  max-height: 11rem;
  overflow-y: auto;
  background: var(--black);
  border: 2px solid var(--border-primary);
}

.member-row {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-xs) var(--spacing-sm);
  cursor: pointer;
  transition: background-color var(--transition-fast);
}

.member-row:hover,
.member-row:focus-within {
  background: var(--hover-bg);
}

.member-row--selected,
.member-row--selected:hover {
  background: var(--active-bg);
  color: var(--text-white);
}

.member-row--selected .member-radio {
  accent-color: var(--text-white);
}

.member-row--selected .member-size {
  color: var(--blue-lighter);
}

.member-row--refused {
  cursor: not-allowed;
  opacity: 0.6;
}

.member-row--refused:hover {
  background: transparent;
}

.member-radio {
  flex: none;
  margin: 0;
  accent-color: var(--blue-primary);
}

.member-name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.8rem;
}

.member-size {
  flex: none;
  font-size: 0.75rem;
}

.member-reason {
  flex: none;
  padding: 0 var(--spacing-xs);
  border: 1px solid var(--status-medium);
  color: var(--status-medium);
  font-size: 0.65rem;
  letter-spacing: 1px;
}

.field-error {
  margin: 0;
  color: var(--status-critical);
  font-size: 0.75rem;
}
</style>
