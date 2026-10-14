export interface Debounced {
  (): void
  cancel: () => void
  /** Runs now what is waiting, if anything is. */
  flush: () => void
}

/** A trailing-edge debounce of a callback that takes no arguments. */
export function debounced(run: () => void, delayMs: number): Debounced {
  let timer: ReturnType<typeof setTimeout> | undefined
  const call = (() => {
    clearTimeout(timer)
    timer = setTimeout(() => {
      timer = undefined
      run()
    }, delayMs)
  }) as Debounced
  call.cancel = () => {
    clearTimeout(timer)
    timer = undefined
  }
  call.flush = () => {
    if (timer === undefined) return
    call.cancel()
    run()
  }
  return call
}
