import { t } from '@/i18n'
import { errorMessage, genericErrorMessage } from '@/services/api-error'

export interface SearchFailure {
  message: string
  status?: number
}

const INVALID_QUERY = 'invalid_query'

interface QueryProblem {
  message: string
  filter_index: number | null
}

function firstQueryProblem(error: unknown): QueryProblem | undefined {
  const envelope = (error as { error?: { code?: unknown; details?: { errors?: unknown } } } | undefined)?.error
  if (envelope?.code !== INVALID_QUERY || !Array.isArray(envelope.details?.errors)) return undefined
  return envelope.details.errors[0] as QueryProblem | undefined
}

/**
 * What to tell the user about a refused or failed events request. A query the API rejects names its
 * first problem (the bar validates first, so this is the exception); a chip is named by position.
 */
export function searchFailure(error: unknown, response?: { status: number }): SearchFailure {
  const problem = firstQueryProblem(error)
  const message =
    problem === undefined
      ? errorMessage(error)
      : problem.filter_index === null
        ? problem.message
        : t('events.search.filterProblem', { position: problem.filter_index + 1, message: problem.message })
  return { message: message === '' ? genericErrorMessage() : message, status: response?.status }
}
