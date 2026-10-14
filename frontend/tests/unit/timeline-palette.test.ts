import { describe, expect, it } from 'vitest'
import { readTimelinePalette } from '@/services/timeline-palette'

describe('the timeline palette', () => {
  const read = (name: string): string => `value of ${name}`

  it('takes the surface, grid and text colours from the design tokens', () => {
    const palette = readTimelinePalette(read)
    expect(palette.background).toBe('value of --dark-bg')
    expect(palette.grid).toBe('value of --border-subtle')
    expect(palette.axisText).toBe('value of --text-gray-dark')
    expect(palette.labelText).toBe('value of --text-gray')
    expect(palette.onAccent).toBe('value of --text-on-primary')
    expect(palette.fontMono).toBe('value of --font-mono')
  })

  it('has the six lane colours under the lane names', () => {
    const palette = readTimelinePalette(read)
    expect(Object.keys(palette.lane)).toEqual(['process', 'file', 'registry', 'network', 'memory', 'api'])
    expect(palette.lane.file).toBe('value of --cat-file')
    expect(palette.lane.api).toBe('value of --cat-api')
  })

  it('has the five severity colours', () => {
    const palette = readTimelinePalette(read)
    expect(palette.severity.critical).toBe('value of --status-critical')
    expect(palette.severity.info).toBe('value of --status-info')
  })

  it('reads each token once', () => {
    const asked: string[] = []
    readTimelinePalette((name) => {
      asked.push(name)
      return ''
    })
    expect(new Set(asked).size).toBe(asked.length)
  })
})
