import type { ArchiveMemberRead } from '@/api'

export const DEFAULT_ARCHIVE_PASSWORD = 'infected'

const ZIP_EXTENSION = /\.zip$/i
const ZIP_MAGIC = 'PK'

/** A zip by its name, else by its first two bytes: a sample is often shared as `.bin` or with no extension. */
export async function isZipFile(file: File): Promise<boolean> {
  if (ZIP_EXTENSION.test(file.name)) return true
  const head = new Uint8Array(await file.slice(0, ZIP_MAGIC.length).arrayBuffer())
  return String.fromCharCode(...head) === ZIP_MAGIC
}

export function isSelectableMember(member: ArchiveMemberRead): boolean {
  return !member.unsafe && !member.unsupported
}

export function hasEncryptedMember(members: ArchiveMemberRead[]): boolean {
  return members.some((member) => member.encrypted)
}
