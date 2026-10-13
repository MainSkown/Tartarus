export function screenshotUrl(analysisId: number, n: number): string {
  return `/api/analyses/${analysisId}/artifacts/screenshots/${n}`
}
