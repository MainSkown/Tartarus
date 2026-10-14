/** Numbers requests so that only the newest one may apply its answer: a slow stale response is dropped. */
export function createRequestSequence() {
  let latest = 0
  return {
    next: (): number => ++latest,
    isCurrent: (request: number): boolean => request === latest,
    invalidate: (): void => {
      latest++
    },
  }
}
