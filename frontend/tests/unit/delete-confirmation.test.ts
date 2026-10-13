import { describe, expect, it } from 'vitest'
import { deleteConfirmation } from '@/services/delete-confirmation'

describe('deleteConfirmation', () => {
  it('names the analysis in the title and the file in the message', () => {
    const { title, message } = deleteConfirmation({ id: 6, filename: 'invoice_scan.exe', disk_bytes: 0 })
    expect(title).toBe('Delete #6')
    expect(message).toContain('Delete invoice_scan.exe?')
  })

  it('says how much disk the delete frees', () => {
    const { message } = deleteConfirmation({ id: 6, filename: 'a.exe', disk_bytes: 5 * 1024 * 1024 })
    expect(message).toContain('freeing 5 MB')
  })

  it('says nothing about size when nothing is stored', () => {
    const { message } = deleteConfirmation({ id: 6, filename: 'a.exe', disk_bytes: 0 })
    expect(message).not.toMatch(/freeing|\bB\b/)
  })

  it('warns that it cannot be undone', () => {
    const { message } = deleteConfirmation({ id: 6, filename: 'a.exe', disk_bytes: 2048 })
    expect(message).toContain('cannot be undone')
  })
})
