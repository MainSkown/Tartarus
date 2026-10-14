import type { Hit } from '@/services/timeline-hit-test'
import { CLUSTER_SIZE, MARK_RING, MARK_SIZE, type Band, type Bar, type ClusterMark, type DetectionMark, type EventMark, type Scene } from '@/services/timeline-layout'
import type { TimelinePalette } from '@/services/timeline-palette'

const FRAME = 2
const OUTLINE_GAP = 3
const TRIANGLE = { width: 12, height: 10 }
const TICK_LENGTH = 4
// Short and at the top of the axis row, so a handle does not cover the tick label at the same x.
const HANDLE = { width: 6, height: 9, top: 1 }
const BAND_ALPHA = 0.16
const STALE_ALPHA = 0.5
const LABEL_FONT_PX = 10
const AXIS_FONT_PX = 11
const INSIDE_LABEL_MIN_HEIGHT = 12
const LABEL_GAP = 3
const BRUSH_LABEL_CHAR_PX = 6.2

export interface DrawState {
  /** The time-range chip, or the range being brushed, as a band. */
  band: Band | null
  /** Text for the band while it is being dragged. */
  brushLabel: string | null
  hover: Hit | null
  selectedId: string | null
  /** Where the selected event's time falls on the canvas, when it is in view. */
  selectedX: number | null
  /** Data for an earlier view or filter is still on screen while the new one loads. */
  stale: boolean
}

function line(ctx: CanvasRenderingContext2D, x0: number, y0: number, x1: number, y1: number, color: string): void {
  ctx.strokeStyle = color
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(x0, y0)
  ctx.lineTo(x1, y1)
  ctx.stroke()
}

const crisp = (value: number): number => Math.round(value) + 0.5

function drawGrid(ctx: CanvasRenderingContext2D, scene: Scene, palette: TimelinePalette): void {
  const { layout } = scene
  for (const lane of layout.lanes) line(ctx, 0, crisp(lane.top), layout.width, crisp(lane.top), palette.grid)
  line(ctx, crisp(layout.gutter), 0, crisp(layout.gutter), layout.height, palette.grid)
  for (const tick of scene.ticks) line(ctx, crisp(tick.x), layout.lanes[0]!.top, crisp(tick.x), layout.axis.top, palette.grid)
}

function drawBand(ctx: CanvasRenderingContext2D, band: Band, scene: Scene, palette: TimelinePalette): void {
  const { layout } = scene
  ctx.fillStyle = palette.accent
  ctx.globalAlpha = BAND_ALPHA
  ctx.fillRect(band.x0, 0, band.x1 - band.x0, layout.height)
  ctx.globalAlpha = 1
  for (const [visible, x] of [[band.startVisible, band.x0], [band.endVisible, band.x1]] as const) {
    if (visible) ctx.fillRect(Math.round(x) - 0.5, 0, 1, layout.height)
  }
}

function drawHandles(ctx: CanvasRenderingContext2D, band: Band, scene: Scene, palette: TimelinePalette): void {
  const { axis } = scene.layout
  ctx.fillStyle = palette.accent
  for (const [visible, x] of [[band.startVisible, band.x0], [band.endVisible, band.x1]] as const) {
    if (visible) ctx.fillRect(Math.round(x) - HANDLE.width / 2, axis.top + HANDLE.top, HANDLE.width, HANDLE.height)
  }
  ctx.fillStyle = palette.onAccent
  for (const [visible, x] of [[band.startVisible, band.x0], [band.endVisible, band.x1]] as const) {
    if (visible) ctx.fillRect(Math.round(x) - 0.5, axis.top + HANDLE.top + 2, 1, HANDLE.height - 4)
  }
}

interface LabelBox {
  x: number
  width: number
}

function brushLabelBox(band: Band, label: string, scene: Scene): LabelBox {
  const width = label.length * BRUSH_LABEL_CHAR_PX + 12
  return { x: Math.min(Math.max((band.x0 + band.x1) / 2 - width / 2, scene.layout.gutter), scene.layout.width - width), width }
}

function drawBrushLabel(ctx: CanvasRenderingContext2D, box: LabelBox, label: string, scene: Scene, palette: TimelinePalette): void {
  const { axis } = scene.layout
  ctx.fillStyle = palette.background
  ctx.fillRect(box.x, axis.top + 2, box.width, axis.height - 4)
  ctx.fillStyle = palette.text
  ctx.textAlign = 'center'
  ctx.fillText(label, box.x + box.width / 2, axis.top + axis.height / 2)
}

function drawAxis(ctx: CanvasRenderingContext2D, scene: Scene, palette: TimelinePalette, covered: LabelBox | undefined): void {
  const { layout } = scene
  line(ctx, layout.gutter, crisp(layout.axis.top), layout.width, crisp(layout.axis.top), palette.grid)
  ctx.font = `${AXIS_FONT_PX}px ${palette.fontMono}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  for (const tick of scene.ticks) line(ctx, crisp(tick.x), layout.axis.top, crisp(tick.x), layout.axis.top + TICK_LENGTH, palette.axisText)
  ctx.fillStyle = palette.axisText
  for (const tick of scene.ticks) {
    const half = ctx.measureText(tick.label).width / 2
    const fits = tick.x - half >= layout.gutter && tick.x + half <= layout.width
    const underCover = covered !== undefined && tick.x + half > covered.x && tick.x - half < covered.x + covered.width
    if (fits && !underCover) ctx.fillText(tick.label, tick.x, layout.axis.top + layout.axis.height / 2 + TICK_LENGTH / 2)
  }
}

function drawBars(ctx: CanvasRenderingContext2D, bars: Bar[], palette: TimelinePalette): void {
  ctx.font = `bold ${LABEL_FONT_PX}px ${palette.fontMono}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  for (const bar of bars) {
    ctx.fillStyle = palette.lane[bar.lane] ?? palette.lane.api!
    ctx.fillRect(bar.x, bar.y, bar.width, bar.height)
    if (bar.label === null) continue
    const inside = bar.height >= INSIDE_LABEL_MIN_HEIGHT
    ctx.fillStyle = inside ? palette.onAccent : palette.labelText
    ctx.fillText(bar.label, bar.x + bar.width / 2, inside ? bar.y + bar.height / 2 : bar.y - LABEL_FONT_PX / 2 - LABEL_GAP)
  }
}

function countText(count: number): string {
  return count < 1000 ? String(count) : `${(count / 1000).toFixed(1).replace(/\.0$/, '')}k`
}

function drawClusters(ctx: CanvasRenderingContext2D, clusters: ClusterMark[], palette: TimelinePalette): void {
  ctx.font = `bold ${LABEL_FONT_PX}px ${palette.fontMono}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  const { width, height } = CLUSTER_SIZE
  for (const cluster of clusters) {
    const left = cluster.x - width / 2
    const top = cluster.y - height / 2
    ctx.fillStyle = palette.background
    ctx.fillRect(left, top, width, height)
    ctx.strokeStyle = palette.lane[cluster.lane] ?? palette.lane.api!
    ctx.lineWidth = FRAME
    ctx.strokeRect(left + FRAME / 2, top + FRAME / 2, width - FRAME, height - FRAME)
    ctx.fillStyle = palette.text
    ctx.fillText(countText(cluster.count), cluster.x, cluster.y + 0.5)
  }
}

function drawEventMarks(ctx: CanvasRenderingContext2D, marks: EventMark[], palette: TimelinePalette): void {
  const half = MARK_SIZE / 2
  for (const mark of marks) {
    ctx.fillStyle = palette.background
    ctx.fillRect(mark.x - half - MARK_RING, mark.y - half - MARK_RING, MARK_SIZE + 2 * MARK_RING, MARK_SIZE + 2 * MARK_RING)
    ctx.fillStyle = palette.lane[mark.lane] ?? palette.lane.api!
    ctx.fillRect(mark.x - half, mark.y - half, MARK_SIZE, MARK_SIZE)
  }
}

function trianglePath(ctx: CanvasRenderingContext2D, x: number, y: number, grow: number): void {
  const halfWidth = TRIANGLE.width / 2 + grow
  const halfHeight = TRIANGLE.height / 2 + grow
  ctx.beginPath()
  ctx.moveTo(x - halfWidth, y - halfHeight)
  ctx.lineTo(x + halfWidth, y - halfHeight)
  ctx.lineTo(x, y + halfHeight + grow)
  ctx.closePath()
}

function drawDetections(ctx: CanvasRenderingContext2D, detections: DetectionMark[], palette: TimelinePalette): void {
  for (const detection of detections) {
    trianglePath(ctx, detection.x, detection.y, MARK_RING)
    ctx.fillStyle = palette.background
    ctx.fill()
    trianglePath(ctx, detection.x, detection.y, 0)
    ctx.fillStyle = palette.severity[detection.severity]
    ctx.fill()
  }
}

function outline(ctx: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, color: string, lineWidth: number): void {
  ctx.strokeStyle = color
  ctx.lineWidth = lineWidth
  ctx.strokeRect(x - width / 2 - OUTLINE_GAP, y - height / 2 - OUTLINE_GAP, width + 2 * OUTLINE_GAP, height + 2 * OUTLINE_GAP)
}

function drawSelection(ctx: CanvasRenderingContext2D, scene: Scene, state: DrawState, palette: TimelinePalette): void {
  const { layout } = scene
  if (state.selectedX !== null) line(ctx, crisp(state.selectedX), layout.lanes[0]!.top, crisp(state.selectedX), layout.axis.top, palette.accentLight)
  if (state.selectedId === null) return
  for (const mark of scene.marks) {
    if (mark.kind === 'event' && mark.id === state.selectedId) outline(ctx, mark.x, mark.y, MARK_SIZE, MARK_SIZE, palette.accentLight, 2)
    else if (mark.kind === 'cluster' && mark.ids.includes(state.selectedId)) outline(ctx, mark.x, mark.y, CLUSTER_SIZE.width, CLUSTER_SIZE.height, palette.accentLight, 2)
  }
}

function drawHover(ctx: CanvasRenderingContext2D, hover: Hit | null, palette: TimelinePalette): void {
  if (hover === null) return
  if (hover.kind === 'mark') outline(ctx, hover.mark.x, hover.mark.y, MARK_SIZE, MARK_SIZE, palette.text, 1)
  else if (hover.kind === 'cluster') outline(ctx, hover.mark.x, hover.mark.y, CLUSTER_SIZE.width, CLUSTER_SIZE.height, palette.text, 1)
  else if (hover.kind === 'bar') {
    ctx.strokeStyle = palette.text
    ctx.lineWidth = 1
    ctx.strokeRect(hover.bar.x - 0.5, hover.bar.y - 0.5, hover.bar.width + 1, hover.bar.height + 1)
  } else if (hover.kind === 'detection') outline(ctx, hover.detection.x, hover.detection.y, TRIANGLE.width, TRIANGLE.height, palette.text, 1)
}

/** Paints a scene. Everything it draws with is in `palette`; geometry comes from the scene, which hit-testing reads too. */
export function drawTimeline(ctx: CanvasRenderingContext2D, scene: Scene, state: DrawState, palette: TimelinePalette): void {
  const { layout } = scene
  ctx.fillStyle = palette.background
  ctx.fillRect(0, 0, layout.width, layout.height)
  drawGrid(ctx, scene, palette)

  ctx.save()
  ctx.beginPath()
  ctx.rect(layout.gutter, 0, layout.plotWidth, layout.height)
  ctx.clip()
  ctx.globalAlpha = state.stale ? STALE_ALPHA : 1
  drawBars(ctx, scene.bars, palette)
  drawClusters(ctx, scene.marks.filter((mark): mark is ClusterMark => mark.kind === 'cluster'), palette)
  drawEventMarks(ctx, scene.marks.filter((mark): mark is EventMark => mark.kind === 'event'), palette)
  drawDetections(ctx, scene.detections, palette)
  ctx.globalAlpha = 1
  if (state.band) drawBand(ctx, state.band, scene, palette)
  drawSelection(ctx, scene, state, palette)
  drawHover(ctx, state.hover, palette)
  const labelBox = state.band && state.brushLabel ? brushLabelBox(state.band, state.brushLabel, scene) : undefined
  drawAxis(ctx, scene, palette, labelBox)
  if (state.band) drawHandles(ctx, state.band, scene, palette)
  if (labelBox && state.brushLabel) drawBrushLabel(ctx, labelBox, state.brushLabel, scene, palette)
  ctx.restore()
}
