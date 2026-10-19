import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'
import { guestsClone } from '@/api'
import type { Guest, GuestProfile, GuestResources, ProfileOption } from '@/api'
import { useGuestSubmission, type GuestSubmission } from '@/composables/use-guest-submission'
import { t } from '@/i18n'
import { guestNameProblem, identityProblem, profileDefaults, withoutBlanks, type OptionValues } from '@/services/guest-form'
import { REFUSALS_SHOWN_INLINE } from '@/services/quiet-statuses'
import { useGuestsStore } from '@/stores/guests'

export type CloneStatus = 'loading' | 'failed' | 'unknown' | 'not-ready' | 'ready'

export interface OptionRow {
  option: ProfileOption
  /** The profile does not let a clone change it: shown with the source's value. */
  locked: boolean
}

export type CloneRequest = {
  name: string
  options: OptionValues
  identity: Record<string, string>
  resources: Pick<GuestResources, 'vcpus' | 'ram_mb'>
}

export interface GuestClone {
  status: Ref<CloneStatus>
  loadError: Ref<string | undefined>
  source: ComputedRef<Guest | undefined>
  profile: ComputedRef<GuestProfile | undefined>
  name: Ref<string>
  machine: Ref<string>
  machineEditable: ComputedRef<boolean>
  options: Ref<OptionValues>
  optionRows: ComputedRef<OptionRow[]>
  resources: Ref<GuestResources>
  problems: ComputedRef<Record<string, string>>
  errors: ComputedRef<Record<string, string>>
  canSubmit: ComputedRef<boolean>
  body: ComputedRef<CloneRequest>
  submission: GuestSubmission
  load: () => Promise<void>
  setOption: (key: string, value: unknown) => void
  submit: () => Promise<void>
}

/** The state of the clone form for one source guest and the request it makes, apart from how it is drawn. */
export function useGuestClone(sourceName: string): GuestClone {
  const store = useGuestsStore()

  const status = ref<CloneStatus>('loading')
  const loadError = ref<string>()
  const name = ref('')
  const machine = ref('')
  const options = ref<OptionValues>({})
  const resources = ref<GuestResources>({ vcpus: 0, ram_mb: 0, disk_gb: 0 })

  const source = computed(() => store.byName(sourceName))
  const profile = computed(() => store.profiles.find((candidate) => candidate.id === source.value?.profile))
  const machineEditable = computed(() => profile.value?.clone.computer_name_editable === true)
  const optionRows = computed<OptionRow[]>(() =>
    (profile.value?.options ?? []).map((option) => ({ option, locked: !option.changeable_on_clone })),
  )

  const submission = useGuestSubmission(hasInput)

  function hasInput(field: string): boolean {
    const editable = optionRows.value.filter((row) => !row.locked).map((row) => `options.${row.option.key}`)
    const fixed = ['name', 'resources.vcpus', 'resources.ram_mb', ...(machineEditable.value ? ['identity.machine'] : [])]
    return [...fixed, ...editable].includes(field)
  }

  const problems = computed(() => {
    const found: Record<string, string> = {}
    if (name.value !== '') {
      const nameProblem = guestNameProblem(name.value, store.guests.map((guest) => guest.name))
      if (nameProblem) found.name = nameProblem
    }
    const rule = profile.value?.identity.machine
    const machineProblem = rule && machineEditable.value ? identityProblem(rule, machine.value.trim()) : undefined
    if (machineProblem) found['identity.machine'] = machineProblem
    for (const field of ['vcpus', 'ram_mb'] as const) {
      if (!Number.isInteger(resources.value[field]) || resources.value[field] < 1) {
        found[`resources.${field}`] = t('guests.form.wholeNumber')
      }
    }
    return found
  })
  const errors = computed(() => ({ ...problems.value, ...submission.fieldErrors.value }))
  const canSubmit = computed(() => status.value === 'ready' && name.value !== '' && Object.keys(problems.value).length === 0)

  const body = computed<CloneRequest>(() => {
    const changeable = optionRows.value.filter((row) => !row.locked).map((row) => row.option.key)
    return {
      name: name.value,
      options: Object.fromEntries(changeable.map((key) => [key, options.value[key]])),
      identity: machineEditable.value ? withoutBlanks({ machine: machine.value.trim() }) : {},
      resources: { vcpus: resources.value.vcpus, ram_mb: resources.value.ram_mb },
    }
  })

  function startFromSource(guest: Guest, guestProfile: GuestProfile): void {
    const defaults = profileDefaults(guestProfile)
    const recorded = Object.fromEntries(Object.entries(guest.options ?? {}).filter(([key]) => key in defaults.options))
    options.value = { ...defaults.options, ...recorded }
    resources.value = { ...(guest.resources ?? defaults.resources) }
  }

  async function load(): Promise<void> {
    status.value = 'loading'
    await Promise.all([store.load(), store.loadProfiles()])
    if (store.loadError !== undefined && store.guests.length === 0) {
      loadError.value = store.loadError
      status.value = 'failed'
    } else if (!source.value) {
      status.value = 'unknown'
    } else if (source.value.state !== 'ready') {
      status.value = 'not-ready'
    } else if (!profile.value) {
      loadError.value = t('guests.clone.profileMissing', { profile: source.value.profile, guest: sourceName })
      status.value = 'failed'
    } else {
      startFromSource(source.value, profile.value)
      status.value = 'ready'
    }
  }

  function setOption(key: string, value: unknown): void {
    options.value = { ...options.value, [key]: value }
    submission.clearFieldError(`options.${key}`)
  }

  async function submit(): Promise<void> {
    if (!canSubmit.value) return
    await submission.submit(() => guestsClone({ path: { name: sourceName }, body: body.value, meta: REFUSALS_SHOWN_INLINE }))
  }

  const clearOnEdit = (field: string) => () => submission.clearFieldError(field)
  const sync = { flush: 'sync' } as const
  watch(name, clearOnEdit('name'), sync)
  watch(machine, clearOnEdit('identity.machine'), sync)
  for (const field of ['vcpus', 'ram_mb'] as const) {
    watch(() => resources.value[field], clearOnEdit(`resources.${field}`), sync)
  }

  return {
    status,
    loadError,
    source,
    profile,
    name,
    machine,
    machineEditable,
    options,
    optionRows,
    resources,
    problems,
    errors,
    canSubmit,
    body,
    submission,
    load,
    setOption,
    submit,
  }
}
