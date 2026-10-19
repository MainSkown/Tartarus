export interface SplitPath {
  /** Everything up to and including the last separator; empty for a bare file name. */
  directory: string
  name: string
}

/** Splits a Windows or POSIX path so a view can truncate the directory and always keep the file name. */
export function splitPath(path: string): SplitPath {
  const cut = Math.max(path.lastIndexOf('\\'), path.lastIndexOf('/')) + 1
  return { directory: path.slice(0, cut), name: path.slice(cut) }
}
