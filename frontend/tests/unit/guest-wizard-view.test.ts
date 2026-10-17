import { describe, expect, it } from 'vitest'
import { blockingWarning, cloneSummary, sourceNotReadyMessage } from '@/services/guest-wizard-view'

describe('cloneSummary', () => {
  it('says what a clone does, how long it takes and how much disk it uses', () => {
    expect(cloneSummary('lab1')).toBe(
      "Copies lab1's disk, gives the copy its own identity, takes about 5 minutes and about 22 GB.",
    )
  })
})

describe('blockingWarning', () => {
  it('says a build takes about 15 minutes and blocks analyses until it is done', () => {
    expect(blockingWarning('build')).toBe('The build takes about 15 minutes. No analysis can start until it is done.')
  })

  it('says the same for a clone with its own time', () => {
    expect(blockingWarning('clone')).toBe('The clone takes about 5 minutes. No analysis can start until it is done.')
  })
})

describe('sourceNotReadyMessage', () => {
  it('names the guest and its state', () => {
    expect(sourceNotReadyMessage('lab4', 'building')).toBe('lab4 is building: only a ready guest can be cloned.')
  })
})
