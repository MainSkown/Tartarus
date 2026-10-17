import { describe, expect, it } from 'vitest'
import { countdownDisplay, shownDuration } from '@/services/countdown'

const RUNNING_INTERACTIVE = { interactive: true, running: true }
const RUNNING_PLAIN = { interactive: false, running: true }

describe('countdownDisplay', () => {
  it('shows a dash when the server gave no time', () => {
    expect(countdownDisplay(null, RUNNING_INTERACTIVE)).toEqual({ text: '–', warning: false })
  })

  it('shows the usual duration format', () => {
    expect(countdownDisplay(240, RUNNING_INTERACTIVE)).toEqual({ text: '4m 0s', warning: false })
  })

  it('warns in the last 30 seconds of an interactive run', () => {
    expect(countdownDisplay(31, RUNNING_INTERACTIVE).warning).toBe(false)
    expect(countdownDisplay(30, RUNNING_INTERACTIVE)).toEqual({ text: '30s', warning: true })
  })

  it('says ending instead of zero while an interactive run is still running', () => {
    expect(countdownDisplay(0, RUNNING_INTERACTIVE)).toEqual({ text: 'ending', warning: true })
    expect(countdownDisplay(0.3, RUNNING_INTERACTIVE).text).toBe('ending')
  })

  it('keeps today\'s display for a run that is not interactive: no warning and no ending', () => {
    expect(countdownDisplay(0, RUNNING_PLAIN)).toEqual({ text: '0s', warning: false })
    expect(countdownDisplay(20, RUNNING_PLAIN)).toEqual({ text: '20s', warning: false })
  })

  it('shows zero rather than ending once the interactive run is no longer running', () => {
    expect(countdownDisplay(0, { interactive: true, running: false })).toEqual({ text: '0s', warning: false })
  })
})

describe('shownDuration', () => {
  it('formats a time and shows a dash for none', () => {
    expect(shownDuration(72)).toBe('1m 12s')
    expect(shownDuration(null)).toBe('–')
  })
})
