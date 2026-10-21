import { readonly, shallowRef, watch } from 'vue'
import { iocsAnalyses, type AnalysisHitRead, type IocType } from '@/api'
import { quietOn } from '@/services/quiet-statuses'

export type IocAnalyses =
  | { status: 'loading' }
  | { status: 'seen'; analyses: AnalysisHitRead[] }
  | { status: 'notPivotable' }
  | { status: 'failed' }

type Settled = Exclude<IocAnalyses, { status: 'loading' }>

const UNPROCESSABLE_STATUS = 422

// One request per indicator for the whole session: a table of the same value, or a drawer reopened, asks once.
// A failure is dropped from the cache so the next mount asks again.
const cache = new Map<string, Promise<Settled>>()

async function fetchAnalyses(kind: IocType, value: string): Promise<Settled> {
  try {
    const { data, response } = await iocsAnalyses({
      path: { kind, value },
      meta: quietOn(UNPROCESSABLE_STATUS),
    })
    if (data) return { status: 'seen', analyses: data }
    return response?.status === UNPROCESSABLE_STATUS ? { status: 'notPivotable' } : { status: 'failed' }
  } catch {
    return { status: 'failed' }
  }
}

function settledFor(kind: IocType, value: string): Promise<Settled> {
  const key = JSON.stringify([kind, value])
  const cached = cache.get(key)
  if (cached) return cached
  const pending = fetchAnalyses(kind, value)
  cache.set(key, pending)
  void pending.then((settled) => {
    if (settled.status === 'failed') cache.delete(key)
  })
  return pending
}

/**
 * The analyses whose events hold an indicator, for the link beside each indicator value. Until the
 * answer arrives the state is `loading`; a 422 means the kind cannot be pivoted, not an error.
 */
export function useIocAnalyses(kind: () => IocType, value: () => string) {
  const state = shallowRef<IocAnalyses>({ status: 'loading' })

  watch(
    [kind, value],
    async ([currentKind, currentValue]) => {
      state.value = { status: 'loading' }
      const settled = await settledFor(currentKind, currentValue)
      if (currentKind === kind() && currentValue === value()) state.value = settled
    },
    { immediate: true },
  )

  return readonly(state)
}
