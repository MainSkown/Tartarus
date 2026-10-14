import type { APIRequestContext } from '@playwright/test'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { deleteWhenOver } from '../e2e/delete-when-over'

function fakeRequest(deleteStatuses: number[]) {
  const calls: string[] = []
  const remaining = [...deleteStatuses]
  const request = {
    delete: vi.fn(async (url: string) => {
      calls.push(`DELETE ${url}`)
      return { status: () => remaining.shift() ?? 409 }
    }),
    post: vi.fn(async (url: string) => {
      calls.push(`POST ${url}`)
      return { status: () => 409 }
    }),
  }
  return { request: request as unknown as APIRequestContext, calls }
}

describe('deleteWhenOver', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('deletes a finished analysis with one call', async () => {
    const { request, calls } = fakeRequest([204])
    await deleteWhenOver(request, '7', 60_000)
    expect(calls).toEqual(['DELETE /api/analyses/7'])
  })

  it('tries a cancel and waits while the analysis is active, then deletes it', async () => {
    const { request, calls } = fakeRequest([409, 409, 204])
    const done = deleteWhenOver(request, '7', 60_000)
    await vi.advanceTimersByTimeAsync(10_000)
    await done
    expect(calls).toEqual([
      'DELETE /api/analyses/7',
      'POST /api/analyses/7/cancel',
      'DELETE /api/analyses/7',
      'POST /api/analyses/7/cancel',
      'DELETE /api/analyses/7',
    ])
  })

  it('gives up after the bound with a warning instead of waiting for ever', async () => {
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const { request } = fakeRequest([])
    const done = deleteWhenOver(request, '7', 9000)
    await vi.advanceTimersByTimeAsync(20_000)
    await done
    expect(warning).toHaveBeenCalledWith(expect.stringContaining('analysis 7 was still active'))
  })
})
