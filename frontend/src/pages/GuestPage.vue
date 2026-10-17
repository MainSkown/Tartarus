<script setup lang="ts">
import GuestCard from '@/components/guest/GuestCard.vue'
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import ViewState from '@/components/ViewState.vue'
import { useGuestList } from '@/composables/use-guest-list'

const list = useGuestList()
</script>

<template>
  <div class="guest-page">
    <div class="guest-header">
      <h1 class="section-title text-mono">
        GUEST VM
      </h1>
      <q-btn
        outline
        square
        label="[+ NEW GUEST]"
        class="new-guest-btn text-mono"
        to="/guest/new"
      />
    </div>

    <p
      v-if="list.loadError.value"
      class="guest-note text-mono"
      role="alert"
    >
      &gt; guest control service is not reachable
    </p>

    <ViewState
      :loading="list.loading.value"
      :error="list.guests.value.length === 0 ? list.loadError.value : undefined"
      @retry="list.reload"
    >
      <ul
        v-if="list.guests.value.length > 0"
        class="guest-grid"
      >
        <li
          v-for="guest in list.guests.value"
          :key="guest.name"
        >
          <GuestCard
            :guest="guest"
            :profile="list.profileOf(guest)"
            :is-default="guest.name === list.defaultName.value"
            :build="list.buildOf(guest.name)"
            :check="list.checkOf(guest.name)"
            :deleting="list.isDeleting(guest.name)"
            :delete-error="list.deleteErrorOf(guest.name)"
            @run-checks="list.runChecks(guest.name)"
            @remove="list.remove(guest.name)"
          />
        </li>
      </ul>

      <div
        v-else-if="!list.loadError.value"
        class="guest-empty text-mono"
      >
        <TerminalEmpty message="guest VM not built" />
        <p class="guest-empty__hint text-gray">
          Put a Windows ISO in <code>data/iso</code>, then build the guest from it.
        </p>
        <q-btn
          outline
          square
          label="[BUILD GUEST]"
          class="new-guest-btn text-mono"
          to="/guest/new"
        />
      </div>
    </ViewState>
  </div>
</template>

<style scoped>
.guest-page {
  padding: var(--spacing-lg);
}

.guest-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-lg);
}

.section-title {
  color: var(--blue-primary);
  font-size: 0.9rem;
  /* Quasar's typography gives h1 a 6rem line-height, which shrinking the font doesn't undo. */
  line-height: 1.2;
  letter-spacing: 2px;
  margin: 0;
}

.guest-note {
  margin: 0 0 var(--spacing-md);
  color: var(--status-critical);
}

.guest-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 26rem), 1fr));
  gap: var(--spacing-md);
  margin: 0;
  padding: 0;
  list-style: none;
}

.guest-grid > li {
  display: flex;
  min-width: 0;
}

.guest-grid > li > * {
  flex: 1;
}

.guest-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-md);
  padding: var(--spacing-xl) 0;
}

.guest-empty :deep(.terminal-empty) {
  padding: 0;
}

.guest-empty__hint {
  margin: 0;
  max-width: 60ch;
  text-align: center;
}

.new-guest-btn {
  color: var(--blue-primary);
}
</style>
