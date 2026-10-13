export interface Size {
  width: number
  height: number
}

/** The factor that fits `guest` inside `container`, or undefined while either has no size yet. */
export function fitScale(container: Size, guest: Size): number | undefined {
  if (container.width <= 0 || container.height <= 0 || guest.width <= 0 || guest.height <= 0) return undefined
  return Math.min(container.width / guest.width, container.height / guest.height)
}
