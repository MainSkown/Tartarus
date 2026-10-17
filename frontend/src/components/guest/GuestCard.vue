<script setup lang="ts">
import { computed, ref } from 'vue'
import type { BuildView, Guest, GuestProfile } from '@/api'
import CopyButton from '@/components/CopyButton.vue'
import GuestBadges from '@/components/guest/GuestBadges.vue'
import GuestChecks from '@/components/guest/GuestChecks.vue'
import GuestField from '@/components/guest/GuestField.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import type { CheckState } from '@/composables/use-guest-list'
import { formatTimestamp } from '@/services/format-time'
import { isInProgress } from '@/services/guest-state'
import { GIVEAWAY_ADVICE, guestActions, kindLabel, resourcesLabel, selfTestOf, systemLabel } from '@/services/guest-view'

const MASKED_PASSWORD = '••••••••'

const props = defineProps<{
  guest: Guest
  profile?: GuestProfile
  edition?: string
  isDefault?: boolean
  build?: BuildView
  check?: CheckState
  deleting?: boolean
  deleteError?: string
}>()
defineEmits<{ runChecks: []; remove: [] }>()

const passwordRevealed = ref(false)

const actions = computed(() => guestActions(props.guest))
const selfTest = computed(() => selfTestOf(props.guest))
const showGiveaways = computed(() => props.guest.adopted && (props.guest.giveaways ?? []).length > 0)
</script>

<template>
  <q-card
    flat
    class="guest-card"
    :class="`guest-card--${guest.state}`"
  >
    <header class="guest-card__head">
      <h2
        class="guest-card__name text-mono"
        :title="guest.name"
      >
        {{ guest.name }}
      </h2>
      <span
        v-if="isDefault"
        class="guest-card__default text-mono"
        title="Analyses run on this guest unless another is chosen"
      >
        <q-icon
          name="star"
          size="14px"
          aria-hidden="true"
        />
        DEFAULT
      </span>
      <StatusBadge
        class="guest-card__state"
        :guest-state="guest.state"
      />
    </header>

    <GuestBadges :badges="guest.badges ?? []" />

    <p
      v-if="guest.error"
      class="guest-card__error text-mono"
      role="alert"
    >
      <q-icon
        name="dangerous"
        size="16px"
        aria-hidden="true"
      />
      <span>{{ guest.error }}</span>
    </p>

    <div
      v-if="isInProgress(guest.state)"
      class="guest-card__progress"
    >
      <progress
        :value="build?.percent"
        max="100"
        :aria-label="`${guest.name} ${guest.state}`"
      />
      <p class="guest-card__progress-text text-mono text-gray">
        <span v-if="build">{{ build.percent }}%</span>
        <span>{{ build?.message || `${guest.state}…` }}</span>
      </p>
    </div>

    <dl class="guest-card__fields">
      <GuestField
        v-if="systemLabel(guest, profile, edition)"
        label="SYSTEM"
      >
        {{ systemLabel(guest, profile, edition) }}
      </GuestField>
      <GuestField
        v-if="kindLabel(guest)"
        label="KIND"
      >
        <span class="text-mono">{{ kindLabel(guest) }}</span>
      </GuestField>
      <GuestField
        v-if="guest.resources"
        label="RESOURCES"
      >
        {{ resourcesLabel(guest.resources) }}
      </GuestField>
      <GuestField
        v-if="guest.ip"
        label="IP"
      >
        <span class="text-mono">{{ guest.ip }}</span>
      </GuestField>
      <template v-if="guest.identity">
        <GuestField label="ACCOUNT">
          <span class="text-mono">{{ guest.identity.account }}</span>
        </GuestField>
        <GuestField label="COMPUTER">
          <span class="text-mono">{{ guest.identity.machine }}</span>
        </GuestField>
        <GuestField label="PASSWORD">
          <span class="guest-card__password">
            <span class="guest-card__secret text-mono">{{ passwordRevealed ? guest.identity.password : MASKED_PASSWORD }}</span>
            <CopyButton
              :text="guest.identity.password"
              what="password"
            />
            <q-btn
              flat
              dense
              square
              :label="passwordRevealed ? '[HIDE]' : '[REVEAL]'"
              :aria-pressed="passwordRevealed"
              class="guest-card__reveal text-mono"
              @click="passwordRevealed = !passwordRevealed"
            />
          </span>
        </GuestField>
      </template>
      <GuestField
        v-if="guest.snapshot"
        label="SNAPSHOT"
      >
        <span class="text-mono">{{ guest.snapshot }}</span>
      </GuestField>
      <GuestField
        v-if="guest.created"
        label="CREATED"
      >
        <span class="text-mono">{{ formatTimestamp(guest.created) }}</span>
      </GuestField>
      <GuestField
        v-if="selfTest"
        label="SELF-TEST"
      >
        <span>{{ selfTest.message }}</span>
        <router-link
          v-if="selfTest.analysisId !== undefined"
          :to="`/analyses/${selfTest.analysisId}`"
          class="guest-card__analysis text-mono"
        >
          analysis #{{ selfTest.analysisId }}
        </router-link>
      </GuestField>
    </dl>

    <div
      v-if="showGiveaways"
      class="guest-card__giveaways"
      role="note"
    >
      <q-icon
        name="warning"
        size="18px"
        aria-hidden="true"
      />
      <div>
        <p class="guest-card__giveaways-title text-mono">
          A SAMPLE CAN TELL THIS IS A SANDBOX
        </p>
        <ul>
          <li
            v-for="giveaway in guest.giveaways"
            :key="giveaway"
            class="text-mono"
          >
            {{ giveaway }}
          </li>
        </ul>
        <p class="guest-card__giveaways-advice">
          {{ GIVEAWAY_ADVICE }}
        </p>
      </div>
    </div>

    <GuestChecks
      v-if="check"
      :state="check"
    />

    <p
      v-if="deleteError"
      class="guest-card__refusal text-mono"
      role="alert"
    >
      <q-icon
        name="dangerous"
        size="16px"
        aria-hidden="true"
      />
      <span>{{ deleteError }}</span>
    </p>

    <div class="guest-card__actions">
      <q-btn
        v-if="actions.runChecks"
        outline
        square
        label="[RUN CHECKS]"
        class="guest-card__action text-mono"
        :loading="check?.busy"
        :disable="check?.busy"
        @click="$emit('runChecks')"
      />
      <q-btn
        v-if="actions.clone"
        outline
        square
        label="[CLONE]"
        class="guest-card__action text-mono"
        :to="`/guest/clone/${guest.name}`"
      />
      <q-btn
        v-if="actions.viewBuild"
        outline
        square
        label="[VIEW BUILD]"
        class="guest-card__action text-mono"
        :to="`/guest/builds/${guest.build_id}`"
      />
      <q-btn
        v-if="actions.remove"
        outline
        square
        label="[DELETE]"
        class="guest-card__delete text-mono"
        :loading="deleting"
        :disable="deleting"
        @click="$emit('remove')"
      />
    </div>
  </q-card>
</template>

<style scoped>
.guest-card {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  min-width: 0;
  padding: var(--spacing-md);
}

.guest-card--failed,
.guest-card--broken {
  border-color: var(--status-critical);
}

.guest-card__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-sm);
}

.guest-card__name {
  flex: 0 1 auto;
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--text-white);
  font-size: 1.1rem;
  font-weight: 600;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.guest-card__default {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  border: 1px solid var(--blue-primary);
  color: var(--blue-primary);
  font-size: 0.75rem;
  letter-spacing: 1px;
}

.guest-card__state {
  margin-left: auto;
}

.guest-card__error,
.guest-card__refusal {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-xs);
  margin: 0;
  color: var(--status-critical);
  font-size: 0.85rem;
  overflow-wrap: anywhere;
}

.guest-card__progress {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.guest-card__progress-text {
  display: flex;
  gap: var(--spacing-sm);
  margin: 0;
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.guest-card__fields {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  margin: 0;
}

.guest-card__password {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-xs) var(--spacing-sm);
}

.guest-card__secret {
  overflow-wrap: anywhere;
}

.guest-card__reveal {
  color: var(--blue-primary);
  font-size: 0.75rem;
}

.guest-card__analysis {
  display: block;
  margin-top: var(--spacing-xs);
  font-size: 0.85rem;
}

.guest-card__giveaways {
  display: flex;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm);
  border: 1px solid var(--status-medium);
  color: var(--status-medium);
  font-size: 0.85rem;
}

.guest-card__giveaways .q-icon {
  flex: none;
}

.guest-card__giveaways > div {
  min-width: 0;
}

.guest-card__giveaways p,
.guest-card__giveaways ul {
  margin: 0;
}

.guest-card__giveaways ul {
  padding-left: var(--spacing-md);
  margin: var(--spacing-xs) 0;
  overflow-wrap: anywhere;
}

.guest-card__giveaways-title {
  font-size: 0.75rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.guest-card__giveaways-advice {
  color: var(--text-gray-light);
}

.guest-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-sm);
  margin-top: auto;
}

.guest-card__action {
  color: var(--blue-primary);
}

.guest-card__delete {
  color: var(--status-critical);
}
</style>
