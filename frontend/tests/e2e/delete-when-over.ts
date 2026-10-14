import type { APIRequestContext } from '@playwright/test'

const RETRY_MS = 3000

/**
 * Deletes an analysis once its run is over. The API refuses (409) while one is active, and only a
 * queued analysis can be cancelled, so each refusal tries a cancel and waits, until the bound. An
 * analysis left running would block the next run's "no analysis is active" precondition; scripts/e2e.sh
 * removes what is left after a bound that gave up.
 */
export async function deleteWhenOver(request: APIRequestContext, id: string, waitMs: number): Promise<void> {
  const deadline = Date.now() + waitMs
  while ((await request.delete(`/api/analyses/${id}`)).status() === 409) {
    if (Date.now() >= deadline) {
      console.warn(`analysis ${id} was still active after ${waitMs / 1000} s and was left for scripts/e2e.sh to remove`)
      return
    }
    await request.post(`/api/analyses/${id}/cancel`)
    await new Promise((resolve) => setTimeout(resolve, RETRY_MS))
  }
}
