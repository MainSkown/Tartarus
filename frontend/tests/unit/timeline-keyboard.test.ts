import { describe, expect, it } from 'vitest'
import { keyCommand } from '@/services/timeline-keyboard'

const press = (key: string, modifiers: { shiftKey?: boolean; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean } = {}) => keyCommand({ key, ...modifiers })

describe('timeline keys', () => {
  it.each([
    ['ArrowLeft', { type: 'pan', fraction: -0.25 }],
    ['ArrowRight', { type: 'pan', fraction: 0.25 }],
    ['+', { type: 'zoom', factor: 0.5 }],
    ['=', { type: 'zoom', factor: 0.5 }],
    ['-', { type: 'zoom', factor: 2 }],
    ['_', { type: 'zoom', factor: 2 }],
    ['0', { type: 'fit' }],
    ['Home', { type: 'jump', edge: 'start' }],
    ['End', { type: 'jump', edge: 'end' }],
    ['Escape', { type: 'escape' }],
  ])('%s', (key, command) => {
    expect(press(key)).toEqual(command)
  })

  it('pans a whole view with shift', () => {
    expect(press('ArrowLeft', { shiftKey: true })).toEqual({ type: 'pan', fraction: -1 })
    expect(press('ArrowRight', { shiftKey: true })).toEqual({ type: 'pan', fraction: 1 })
  })

  it('leaves keys that mean something else alone', () => {
    expect(press('a')).toBeNull()
    expect(press('ArrowUp')).toBeNull()
    expect(press('Tab')).toBeNull()
  })

  it('leaves browser shortcuts such as ctrl and minus (page zoom) to the browser', () => {
    expect(press('-', { ctrlKey: true })).toBeNull()
    expect(press('0', { metaKey: true })).toBeNull()
    expect(press('ArrowLeft', { altKey: true })).toBeNull()
  })
})
