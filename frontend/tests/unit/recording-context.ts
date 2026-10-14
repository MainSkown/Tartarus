export interface Op {
  name: string
  args: unknown[]
  fillStyle: string
  strokeStyle: string
  alpha: number
  inClip: boolean
}

/** A canvas context that only records what is asked of it, with the style in force at each call. */
export class RecordingContext {
  ops: Op[] = []
  fillStyle = ''
  strokeStyle = ''
  lineWidth = 1
  font = ''
  textAlign = ''
  textBaseline = ''
  globalAlpha = 1
  private clips = 0
  private saved: number[] = []

  private record(name: string, args: unknown[]): void {
    this.ops.push({ name, args, fillStyle: this.fillStyle, strokeStyle: this.strokeStyle, alpha: this.globalAlpha, inClip: this.clips > 0 })
  }

  save(): void {
    this.saved.push(this.clips)
  }

  restore(): void {
    this.clips = this.saved.pop() ?? 0
    this.globalAlpha = 1
  }

  clip(): void {
    this.clips++
  }

  beginPath = (): void => this.record('beginPath', [])
  rect = (...args: number[]): void => this.record('rect', args)
  moveTo = (...args: number[]): void => this.record('moveTo', args)
  lineTo = (...args: number[]): void => this.record('lineTo', args)
  closePath = (): void => this.record('closePath', [])
  fill = (): void => this.record('fill', [])
  stroke = (): void => this.record('stroke', [])
  fillRect = (...args: number[]): void => this.record('fillRect', args)
  strokeRect = (...args: number[]): void => this.record('strokeRect', args)
  fillText = (...args: unknown[]): void => this.record('fillText', args)
  clearRect = (...args: number[]): void => this.record('clearRect', args)
  setLineDash = (): void => undefined
  measureText = (text: string): { width: number } => ({ width: text.length * 6.6 })
  setTransform = (...args: number[]): void => this.record('setTransform', args)
}
