import { describe, expect, it } from 'vitest'
import { groupAnnotations } from '@/services/annotation-groups'
import { noteAnnotation, tagAnnotation } from './annotation-fixtures'

describe('groupAnnotations', () => {
  it('has nothing to show for an analysis without annotations', () => {
    expect(groupAnnotations([], [])).toEqual({ analysis: undefined, processes: [], events: [] })
  })

  it('puts the tags and notes of the analysis in one entry', () => {
    const tag = tagAnnotation({ tag: 'phishing' })
    const note = noteAnnotation()
    const { analysis } = groupAnnotations([tag], [note])
    expect(analysis).toEqual({ target: { type: 'analysis', ref: '' }, orphaned: false, tags: [tag], notes: [note] })
  })

  it('makes one entry per process, by pid, with its tags and notes together', () => {
    const tag9 = tagAnnotation({ target_type: 'process', target_ref: '9708' })
    const tag2 = tagAnnotation({ target_type: 'process', target_ref: '2476' })
    const note9 = noteAnnotation({ target_type: 'process', target_ref: '9708' })
    const { processes } = groupAnnotations([tag9, tag2], [note9])
    expect(processes.map((entry) => entry.target.ref)).toEqual(['2476', '9708'])
    expect(processes[1]).toMatchObject({ tags: [tag9], notes: [note9] })
  })

  it('makes one entry per event, in the order they were first annotated', () => {
    const second = tagAnnotation({ target_type: 'event', target_ref: 'bbb' })
    const first = noteAnnotation({ target_type: 'event', target_ref: 'aaa' })
    const { events } = groupAnnotations([second], [first])
    expect(events.map((entry) => entry.target.ref)).toEqual(['bbb', 'aaa'])
  })

  it('marks an entry orphaned when its target is gone', () => {
    const tag = tagAnnotation({ target_type: 'event', target_ref: 'gone', orphaned: true })
    const note = noteAnnotation({ target_type: 'event', target_ref: 'gone', orphaned: true })
    const alive = tagAnnotation({ target_type: 'event', target_ref: 'here' })
    const { events } = groupAnnotations([tag, alive], [note])
    expect(events.map((entry) => [entry.target.ref, entry.orphaned])).toEqual([
      ['gone', true],
      ['here', false],
    ])
  })
})
