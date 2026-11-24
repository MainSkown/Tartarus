<script setup lang="ts">
import type { LanHostSummary } from '@/api'
import CopyButton from '@/components/CopyButton.vue'
import HashRow from '@/components/HashRow.vue'
import PaneHeading from '@/components/PaneHeading.vue'
import { t } from '@/i18n'
import { formatFileSize } from '@/services/file-size'
import { formatClockTime, formatTimestamp } from '@/services/format-time'
import { formatCount } from '@/services/format-number'

defineProps<{ host: LanHostSummary }>()

const NOTHING = '–'

function attemptsText(count: number): string {
  return t('analysis.summary.lan.attempts', { count: formatCount(count) }, count)
}
</script>

<template>
  <article class="lan-host">
    <PaneHeading :label="host.fqdn">
      <span class="lan-host__identity text-mono text-gray">
        <span>{{ host.address }}</span>
        <span>{{ host.role }}</span>
      </span>
    </PaneHeading>
    <p class="lan-host__span text-mono text-gray">
      {{ t('analysis.summary.lan.firstLast', { first: formatTimestamp(host.first), last: formatTimestamp(host.last) }) }}
    </p>

    <section class="lan-host__block">
      <h4 class="lan-host__label text-mono">
        {{ t('analysis.summary.lan.services.label') }}
      </h4>
      <div class="tt-table-scroll">
        <table class="tt-table lan-services text-mono">
          <thead>
            <tr>
              <th>{{ t('analysis.summary.lan.services.service') }}</th>
              <th class="num">
                {{ t('analysis.summary.lan.services.port') }}
              </th>
              <th class="num">
                {{ t('analysis.summary.lan.services.attempts') }}
              </th>
              <th>{{ t('analysis.summary.lan.services.first') }}</th>
              <th>{{ t('analysis.summary.lan.services.last') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(service, index) in host.services"
              :key="`${service.service}-${service.port}-${index}`"
            >
              <td>
                <template v-if="service.service !== null">
                  {{ service.service }}
                </template>
                <span
                  v-else
                  class="cell-empty"
                >{{ t('analysis.summary.lan.services.notServed') }}</span>
              </td>
              <td class="num">
                <template v-if="service.port !== null">
                  {{ service.port }}
                </template>
                <span
                  v-else
                  class="cell-empty"
                >{{ NOTHING }}</span>
              </td>
              <td class="num">
                {{ attemptsText(service.attempts) }}
              </td>
              <td>{{ formatClockTime(service.first) }}</td>
              <td>{{ formatClockTime(service.last) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section
      v-if="host.credentials.length > 0"
      class="lan-host__block"
    >
      <h4 class="lan-host__label text-mono">
        {{ t('analysis.summary.lan.credentials.label') }}
      </h4>
      <ul class="lan-host__list">
        <li
          v-for="(credential, index) in host.credentials"
          :key="`${credential.user}-${credential.domain}-${credential.mechanism}-${index}`"
          class="lan-credential"
        >
          <div class="lan-credential__line text-mono">
            <span
              class="lan-credential__mark"
              :class="credential.success ? 'lan-credential__mark--accepted' : 'lan-credential__mark--refused'"
            >
              <q-icon
                :name="credential.success ? 'check_circle' : 'block'"
                size="14px"
                aria-hidden="true"
              />
              <span class="lan-credential__result">{{ credential.success ? t('analysis.summary.lan.credentials.accepted') : t('analysis.summary.lan.credentials.refused') }}</span>
            </span>
            <span
              v-if="credential.user !== ''"
              class="lan-credential__user"
            >{{ credential.user }}</span>
            <span
              v-else
              class="lan-credential__user cell-empty"
            >{{ t('analysis.summary.lan.credentials.unattributed') }}</span>
            <span
              v-if="credential.domain !== ''"
              class="lan-credential__detail text-gray"
            >{{ credential.domain }}</span>
            <span
              v-if="credential.mechanism !== ''"
              class="lan-credential__detail text-gray"
            >{{ credential.mechanism }}</span>
            <span class="lan-credential__detail text-gray">{{ attemptsText(credential.count) }}</span>
          </div>
          <div
            v-if="credential.secret_as_sent !== null"
            class="lan-credential__secret-block"
          >
            <span class="lan-host__label text-mono">{{ t('analysis.summary.lan.credentials.secretLabel') }}</span>
            <div class="lan-credential__secret-line">
              <code
                class="lan-credential__secret text-mono"
                :title="credential.secret_as_sent"
              >{{ credential.secret_as_sent }}</code>
              <CopyButton
                :text="credential.secret_as_sent"
                :what="t('analysis.summary.lan.credentials.secretWhat')"
              />
            </div>
          </div>
        </li>
      </ul>
      <p
        v-if="(host.credentials_more ?? 0) > 0"
        class="lan-host__more text-mono text-gray"
      >
        {{ t('analysis.summary.lan.credentials.more', { count: formatCount(host.credentials_more ?? 0) }, host.credentials_more ?? 0) }}
      </p>
    </section>

    <section
      v-if="host.files.length > 0"
      class="lan-host__block"
    >
      <h4 class="lan-host__label text-mono">
        {{ t('analysis.summary.lan.files.label') }}
      </h4>
      <ul class="lan-host__list">
        <li
          v-for="(file, index) in host.files"
          :key="`${file.share}-${file.path}-${index}`"
          class="lan-file"
        >
          <span class="lan-file__path text-mono">{{ file.path }}</span>
          <span class="lan-file__meta text-mono text-gray">
            <span class="lan-file__share">{{ t('analysis.summary.lan.files.share', { share: file.share }) }}</span>
            <span class="lan-file__size">{{ file.size === null ? NOTHING : formatFileSize(file.size) }}</span>
          </span>
          <HashRow
            :label="t('analysis.summary.lan.files.sha256')"
            :hash="file.sha256"
          />
        </li>
      </ul>
      <p
        v-if="(host.files_more ?? 0) > 0"
        class="lan-host__more text-mono text-gray"
      >
        {{ t('analysis.summary.lan.files.more', { count: formatCount(host.files_more ?? 0) }, host.files_more ?? 0) }}
      </p>
    </section>
  </article>
</template>

<style scoped>
.lan-host {
  min-width: 0;
  padding: var(--spacing-sm) var(--spacing-md) var(--spacing-md);
  border: 1px solid var(--border-primary);
  background: var(--dark-bg);
}

.lan-host__identity {
  display: flex;
  flex-wrap: wrap;
  gap: 0 var(--spacing-md);
  font-size: 0.75rem;
}

.lan-host__span {
  margin: 0 0 var(--spacing-sm);
  font-size: 0.7rem;
  overflow-wrap: anywhere;
}

.lan-host__block {
  margin-top: var(--spacing-md);
}

.lan-host__label {
  margin: 0 0 var(--spacing-xs);
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.lan-host__block .tt-table-scroll {
  width: fit-content;
  max-width: 100%;
}

.lan-host__list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  margin: 0;
  padding: 0;
  list-style: none;
}

.lan-credential,
.lan-file {
  min-width: 0;
  padding-left: var(--spacing-sm);
  border-left: 2px solid var(--border-primary);
}

.lan-credential__line,
.lan-file__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--spacing-md);
  min-width: 0;
  font-size: 0.8rem;
}

.lan-credential__user,
.lan-file__path {
  font-weight: bold;
  overflow-wrap: anywhere;
}

.lan-file__path {
  display: block;
  color: var(--text-white);
  font-size: 0.8rem;
}

.lan-file__meta {
  font-size: 0.75rem;
}

.lan-file__share {
  min-width: 0;
  overflow-wrap: anywhere;
}

.lan-credential__detail {
  overflow-wrap: anywhere;
}

.lan-credential__mark {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-xs);
  font-size: 0.8rem;
}

.lan-credential__mark--accepted {
  color: var(--status-high);
}

.lan-credential__mark--refused {
  color: var(--text-gray-dark);
}

.lan-credential__secret-block {
  margin-top: var(--spacing-xs);
}

.lan-credential__secret-line {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  min-width: 0;
}

.lan-credential__secret {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 48ch;
  overflow: hidden;
  color: var(--blue-lighter);
  font-size: 0.8rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lan-host__more {
  margin: var(--spacing-xs) 0 0;
  font-size: 0.75rem;
}
</style>
