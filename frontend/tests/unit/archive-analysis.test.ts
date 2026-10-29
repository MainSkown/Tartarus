import { describe, expect, it } from 'vitest'
import type { ReportSummary } from '@/api'
import { archiveOf } from '@/services/archive-analysis'
import { analysisFixture } from './analysis-fixtures'

const ENTRY_SHA256 = 'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90'

function archiveAnalysis(entry: unknown, summary: ReportSummary | null = null) {
  return analysisFixture({ filename: 'bundle.zip', options: { archive_entry: entry, package: 'zip' }, summary })
}

describe('archiveOf', () => {
  it('is undefined for an analysis that was not a zip', () => {
    expect(archiveOf(analysisFixture())).toBeUndefined()
    expect(archiveOf(analysisFixture({ options: { timeout: 180 } }))).toBeUndefined()
  })

  it.each([['an empty entry', ''], ['a non-string entry', 7], ['a null entry', null]])('is undefined for %s', (_label, entry) => {
    expect(archiveOf(archiveAnalysis(entry))).toBeUndefined()
  })

  it('names the file run and has no hash for it while there is no summary', () => {
    expect(archiveOf(archiveAnalysis('payload/loader.exe'))).toEqual({ entry: 'payload/loader.exe', entrySha256: null })
  })

  it('has no hash when the summary records none', () => {
    const summary: ReportSummary = { sample: { name: 'bundle.zip' } }
    expect(archiveOf(archiveAnalysis('a.dll', summary))?.entrySha256).toBeNull()
    expect(archiveOf(archiveAnalysis('a.dll', { sample: { entry_sha256: null } }))?.entrySha256).toBeNull()
    expect(archiveOf(archiveAnalysis('a.dll', {}))?.entrySha256).toBeNull()
  })

  it('carries the SHA-256 of the file that ran', () => {
    const summary: ReportSummary = { sample: { entry_sha256: ENTRY_SHA256 } }
    expect(archiveOf(archiveAnalysis('loader.exe', summary))).toEqual({ entry: 'loader.exe', entrySha256: ENTRY_SHA256 })
  })
})
