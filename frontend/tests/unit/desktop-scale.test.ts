import { describe, expect, it } from 'vitest'
import { fitScale } from '@/services/desktop-scale'

describe('fitScale', () => {
  const guest = { width: 1280, height: 800 }

  it('fits a wide container by its height', () => {
    expect(fitScale({ width: 2000, height: 400 }, guest)).toBeCloseTo(0.5)
  })

  it('fits a tall container by its width', () => {
    expect(fitScale({ width: 640, height: 2000 }, guest)).toBeCloseTo(0.5)
  })

  it('scales up when the container is larger than the guest, as fullscreen is', () => {
    expect(fitScale({ width: 2560, height: 1600 }, guest)).toBeCloseTo(2)
  })

  it.each([
    [{ width: 0, height: 400 }, guest],
    [{ width: 400, height: 0 }, guest],
    [{ width: 400, height: 400 }, { width: 0, height: 800 }],
    [{ width: 400, height: 400 }, { width: 1280, height: 0 }],
  ])('keeps the display where it is for a zero size (%j, %j)', (container, size) => {
    expect(fitScale(container, size)).toBeUndefined()
  })
})
