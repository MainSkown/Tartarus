import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'
import { guestsMedia, guestsStartBuild } from '@/api'
import type { GuestProfile, GuestResources, MediaEntry } from '@/api'
import { useGuestSubmission, type GuestSubmission } from '@/composables/use-guest-submission'
import { t } from '@/i18n'
import { errorMessage } from '@/services/api-error'
import {
  BLANK_IDENTITY_LABEL,
  guestNameProblem,
  identityProblem,
  optionValueLabel,
  profileDefaults,
  resourceProblems,
  withoutBlanks,
  type OptionValues,
} from '@/services/guest-form'
import { variantLabel } from '@/services/guest-media-view'
import { quietOn } from '@/services/quiet-statuses'
import { resourcesLabel } from '@/services/guest-view'
import { useGuestsStore } from '@/stores/guests'

export type WizardStep = 1 | 2 | 3
export type LoadStatus = 'loading' | 'loaded' | 'failed'

const LAST_STEP: WizardStep = 3
// Shown inline on the review step, so a toast on top would only repeat them.
const REFUSALS_SHOWN_INLINE = quietOn(409, 422, 502, 503, 504)

export interface MediaChoice {
  entry: MediaEntry
  profileName?: string
  /** Why the image cannot be built from: what the scan said, or that no installed profile reads it. */
  unavailable?: string
}

export interface VariantChoice {
  value: number
  label: string
}

export interface ReviewRow {
  label: string
  value: string
  /** Left for the build to choose: shown as such, not as a value the analyst typed. */
  blank: boolean
}

export type BuildRequest = {
  profile: string
  name: string
  media: { file: string; variant?: string }
  options: OptionValues
  identity: Record<string, string>
  resources: GuestResources
}

export interface GuestWizard {
  step: Ref<WizardStep>
  mediaStatus: Ref<LoadStatus>
  mediaError: Ref<string | undefined>
  mediaChoices: ComputedRef<MediaChoice[]>
  selectedMedia: ComputedRef<MediaEntry | undefined>
  profile: ComputedRef<GuestProfile | undefined>
  variantIndex: Ref<number | undefined>
  variantChoices: ComputedRef<VariantChoice[]>
  name: Ref<string>
  account: Ref<string>
  machine: Ref<string>
  password: Ref<string>
  options: Ref<OptionValues>
  resources: Ref<GuestResources>
  /** What the form can already tell is wrong, by field path; nothing for a field still empty. */
  problems: ComputedRef<Record<string, string>>
  /** The server's refusals over `problems`, by field path: what an input shows. */
  errors: ComputedRef<Record<string, string>>
  canContinue: ComputedRef<boolean>
  body: ComputedRef<BuildRequest>
  reviewRows: ComputedRef<ReviewRow[]>
  submission: GuestSubmission
  load: () => Promise<void>
  selectMedia: (file: string) => void
  setOption: (key: string, value: unknown) => void
  next: () => void
  back: () => void
  goTo: (step: number) => void
  submit: () => Promise<void>
}

/** The media is chosen on step 1; every other field, including the edition, is on step 2. */
export function stepOfField(field: string): WizardStep {
  return field === 'media.file' ? 1 : 2
}

/** The state of the build wizard and the request it makes, apart from how it is drawn. */
export function useGuestWizard(): GuestWizard {
  const store = useGuestsStore()

  const step = ref<WizardStep>(1)
  const mediaStatus = ref<LoadStatus>('loading')
  const mediaError = ref<string>()
  const media = ref<MediaEntry[]>([])

  const selectedFile = ref<string>()
  const variantIndex = ref<number>()
  const name = ref('')
  const account = ref('')
  const machine = ref('')
  const password = ref('')
  const options = ref<OptionValues>({})
  const resources = ref<GuestResources>({ vcpus: 0, ram_mb: 0, disk_gb: 0 })

  function profileById(id: string | null | undefined): GuestProfile | undefined {
    return store.profiles.find((candidate) => candidate.id === id)
  }

  const mediaChoices = computed<MediaChoice[]>(() =>
    media.value.map((entry) => {
      const profile = profileById(entry.profile)
      const noProfile = entry.profile ? t('guests.wizard.noProfile', { profile: entry.profile }) : undefined
      return { entry, profileName: profile?.display_name, unavailable: entry.error ?? (profile ? undefined : noProfile) }
    }),
  )
  const selectedMedia = computed(() => media.value.find((entry) => entry.file === selectedFile.value))
  const profile = computed(() => profileById(selectedMedia.value?.profile))

  const variantChoices = computed<VariantChoice[]>(() =>
    (selectedMedia.value?.variants ?? []).map((variant) => ({
      value: variant.index,
      label: variantLabel(variant, selectedMedia.value?.language),
    })),
  )
  const chosenVariant = computed(() => variantChoices.value.find((choice) => choice.value === variantIndex.value))

  const submission = useGuestSubmission(hasInput)

  function hasInput(field: string): boolean {
    const optionKeys = (profile.value?.options ?? []).map((option) => `options.${option.key}`)
    const fixed = ['name', 'media.file', 'media.variant', 'identity.account', 'identity.machine', 'identity.password']
    return [...fixed, ...optionKeys, 'resources.vcpus', 'resources.ram_mb', 'resources.disk_gb'].includes(field)
  }

  const problems = computed(() => {
    const found: Record<string, string> = {}
    const nameProblem = name.value === '' ? undefined : guestNameProblem(name.value, store.guests.map((guest) => guest.name))
    if (nameProblem) found.name = nameProblem
    const rules = profile.value?.identity
    if (rules) {
      const typed = { account: account.value.trim(), machine: machine.value.trim(), password: password.value }
      for (const role of ['account', 'machine', 'password'] as const) {
        const problem = identityProblem(rules[role], typed[role])
        if (problem) found[`identity.${role}`] = problem
      }
    }
    const minDisk = profile.value?.resources.min_disk_gb ?? 1
    for (const [field, problem] of Object.entries(resourceProblems(resources.value, minDisk))) found[`resources.${field}`] = problem
    return found
  })
  const errors = computed(() => ({ ...problems.value, ...submission.fieldErrors.value }))

  const settingsReady = computed(() => {
    const editionChosen = variantChoices.value.length === 0 || chosenVariant.value !== undefined
    return name.value !== '' && editionChosen && Object.keys(problems.value).length === 0
  })
  const canContinue = computed(() => {
    if (!selectedMedia.value || !profile.value) return false
    return step.value === 1 || settingsReady.value
  })

  const body = computed<BuildRequest>(() => ({
    profile: profile.value?.id ?? '',
    name: name.value,
    media: { file: selectedFile.value ?? '', ...(chosenVariant.value ? { variant: String(chosenVariant.value.value) } : {}) },
    options: { ...options.value },
    identity: withoutBlanks({ account: account.value.trim(), machine: machine.value.trim(), password: password.value }),
    resources: { ...resources.value },
  }))

  const reviewRows = computed<ReviewRow[]>(() => {
    const identity = body.value.identity
    const identityRow = (label: string, key: string, shown: string): ReviewRow =>
      key in identity ? { label, value: shown, blank: false } : { label, value: t(BLANK_IDENTITY_LABEL), blank: true }
    const optionRows = (profile.value?.options ?? []).map((option) => ({
      label: option.label,
      value: optionValueLabel(option, options.value[option.key]),
      blank: false,
    }))
    return [
      { label: t('guests.review.media'), value: selectedFile.value ?? '', blank: false },
      ...(chosenVariant.value ? [{ label: t('guests.review.edition'), value: chosenVariant.value.label, blank: false }] : []),
      { label: t('guests.review.name'), value: name.value, blank: false },
      identityRow(t('guests.review.username'), 'account', identity.account ?? ''),
      identityRow(t('guests.review.computerName'), 'machine', identity.machine ?? ''),
      identityRow(t('guests.review.password'), 'password', t('guests.review.passwordSetByYou')),
      { label: t('guests.review.resources'), value: resourcesLabel(resources.value), blank: false },
      ...optionRows,
    ]
  })

  async function load(): Promise<void> {
    mediaStatus.value = 'loading'
    const [{ data, error }] = await Promise.all([guestsMedia(), store.loadProfiles(), store.load()])
    if (data && !error) {
      media.value = data
      mediaStatus.value = 'loaded'
    } else {
      mediaError.value = errorMessage(error)
      mediaStatus.value = 'failed'
    }
  }

  function selectMedia(file: string): void {
    const choice = mediaChoices.value.find((candidate) => candidate.entry.file === file)
    if (!choice || choice.unavailable || file === selectedFile.value) return
    selectedFile.value = file
    variantIndex.value = choice.entry.variants?.[0]?.index
    const defaults = profileDefaults(profileById(choice.entry.profile)!)
    options.value = defaults.options
    resources.value = defaults.resources
  }

  function setOption(key: string, value: unknown): void {
    options.value = { ...options.value, [key]: value }
    submission.clearFieldError(`options.${key}`)
  }

  function next(): void {
    if (canContinue.value && step.value < LAST_STEP) step.value = (step.value + 1) as WizardStep
  }

  function back(): void {
    if (step.value > 1) step.value = (step.value - 1) as WizardStep
  }

  function goTo(target: number): void {
    if (target >= 1 && target < step.value) step.value = target as WizardStep
  }

  async function submit(): Promise<void> {
    if (step.value !== LAST_STEP || !canContinue.value) return
    const refused = await submission.submit(() => guestsStartBuild({ body: body.value, meta: REFUSALS_SHOWN_INLINE }))
    if (refused.length > 0) step.value = Math.min(...refused.map(stepOfField)) as WizardStep
  }

  const clearOnEdit = (field: string) => () => submission.clearFieldError(field)
  const sync = { flush: 'sync' } as const
  watch(selectedFile, clearOnEdit('media.file'), sync)
  watch(variantIndex, clearOnEdit('media.variant'), sync)
  watch(name, clearOnEdit('name'), sync)
  watch(account, clearOnEdit('identity.account'), sync)
  watch(machine, clearOnEdit('identity.machine'), sync)
  watch(password, clearOnEdit('identity.password'), sync)
  for (const field of ['vcpus', 'ram_mb', 'disk_gb'] as const) {
    watch(() => resources.value[field], clearOnEdit(`resources.${field}`), sync)
  }

  return {
    step,
    mediaStatus,
    mediaError,
    mediaChoices,
    selectedMedia,
    profile,
    variantIndex,
    variantChoices,
    name,
    account,
    machine,
    password,
    options,
    resources,
    problems,
    errors,
    canContinue,
    body,
    reviewRows,
    submission,
    load,
    selectMedia,
    setOption,
    next,
    back,
    goTo,
    submit,
  }
}
