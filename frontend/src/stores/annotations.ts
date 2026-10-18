import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  annotationsAddNote,
  annotationsAddTag,
  annotationsDeleteNote,
  annotationsRead,
  annotationsRemoveTag,
  annotationsUpdateNote,
} from '@/api'
import type { NoteAnnotation, TagAnnotation, TargetType } from '@/api'
import { t } from '@/i18n'
import { errorMessage } from '@/services/api-error'
import { quietOn } from '@/services/quiet-statuses'
import { refusalMessage } from '@/services/validation-errors'
import { useAnalysesStore } from '@/stores/analyses'

export interface AnnotationTarget {
  type: TargetType
  ref: string
}

export const ANALYSIS_TARGET: AnnotationTarget = { type: 'analysis', ref: '' }
export const processTarget = (pid: number): AnnotationTarget => ({ type: 'process', ref: String(pid) })
export const eventTarget = (id: string): AnnotationTarget => ({ type: 'event', ref: id })

const CONFLICT_STATUS = 409
const UNPROCESSABLE_STATUS = 422

const isOn = (target: AnnotationTarget) => (annotation: { target_type: TargetType; target_ref: string }) =>
  annotation.target_type === target.type && annotation.target_ref === target.ref

/**
 * Every tag and note of the analysis the workspace has open, read once and kept in step with
 * what the analyst changes. The editors, the Notes tab and the Dashboard row all read this one
 * copy, so a tag added in the drawer shows in the Notes tab with no second request.
 */
export const useAnnotationsStore = defineStore('annotations', () => {
  const analysisId = ref<number>()
  const tags = ref<TagAnnotation[]>([])
  const notes = ref<NoteAnnotation[]>([])
  const loading = ref(false)
  const loadError = ref<string>()

  let inFlight: Promise<void> | undefined
  // A read is applied only while it is for the analysis now open, so a slow answer for the one
  // the analyst has already left can never fill the new one's editors.
  let readId = 0

  async function read(id: number): Promise<void> {
    const request = ++readId
    loading.value = true
    const { data, error } = await annotationsRead({ path: { analysis_id: id } })
    if (request !== readId) return
    loading.value = false
    loadError.value = error || !data ? errorMessage(error) : undefined
    if (data && !error) {
      tags.value = data.tags
      notes.value = data.notes
    }
  }

  function start(id: number): Promise<void> {
    if (analysisId.value !== id) {
      analysisId.value = id
      tags.value = []
      notes.value = []
    }
    loadError.value = undefined
    const pending = read(id).finally(() => {
      if (inFlight === pending) inFlight = undefined
    })
    inFlight = pending
    return pending
  }

  function ensureLoaded(id: number): Promise<void> {
    const held = analysisId.value === id && (inFlight !== undefined || !loadError.value)
    return held ? (inFlight ?? Promise.resolve()) : start(id)
  }

  function reload(): Promise<void> {
    return analysisId.value === undefined ? Promise.resolve() : start(analysisId.value)
  }

  const tagsOf = (target: AnnotationTarget): TagAnnotation[] => tags.value.filter(isOn(target))
  const noteOf = (target: AnnotationTarget): NoteAnnotation | undefined => notes.value.find(isOn(target))

  function shareAnalysisTags(): void {
    if (analysisId.value === undefined) return
    const names = tagsOf(ANALYSIS_TARGET).map((link) => link.tag).sort()
    useAnalysesStore().setTags(analysisId.value, names)
  }

  /** Resolves to the message to show beside the input, or `undefined` when the tag was added. */
  async function addTag(target: AnnotationTarget, name: string): Promise<string | undefined> {
    if (analysisId.value === undefined) return undefined
    if (tagsOf(target).some((link) => link.tag === name)) return t('tags.input.duplicate')
    const { data, error } = await annotationsAddTag({
      path: { analysis_id: analysisId.value },
      body: { target_type: target.type, target_ref: target.ref, tag: name },
      meta: quietOn(CONFLICT_STATUS, UNPROCESSABLE_STATUS),
    })
    if (error || !data) return refusalMessage(error)
    tags.value = [...tags.value, data]
    if (target.type === 'analysis') shareAnalysisTags()
    return undefined
  }

  async function removeTag(linkId: number): Promise<boolean> {
    if (analysisId.value === undefined) return false
    const { error } = await annotationsRemoveTag({ path: { analysis_id: analysisId.value, link_id: linkId } })
    if (error) return false
    const removed = tags.value.find((link) => link.link_id === linkId)
    tags.value = tags.value.filter((link) => link.link_id !== linkId)
    if (removed?.target_type === 'analysis') shareAnalysisTags()
    return true
  }

  async function deleteNote(noteId: number): Promise<boolean> {
    const { error } = await annotationsDeleteNote({ path: { note_id: noteId } })
    if (error) return false
    notes.value = notes.value.filter((note) => note.id !== noteId)
    return true
  }

  async function updateNote(note: NoteAnnotation, body: string): Promise<boolean> {
    const { data, error } = await annotationsUpdateNote({ path: { note_id: note.id }, body: { body } })
    if (error || !data) return false
    notes.value = notes.value.map((known) => (known.id === data.id ? data : known))
    return true
  }

  async function addNote(target: AnnotationTarget, body: string): Promise<boolean> {
    if (analysisId.value === undefined) return false
    const { data, error } = await annotationsAddNote({
      path: { analysis_id: analysisId.value },
      body: { target_type: target.type, target_ref: target.ref, body },
    })
    if (error || !data) return false
    notes.value = [...notes.value, data]
    return true
  }

  /** Saves the target's note: created on the first text, replaced after, deleted when cleared. */
  async function saveNote(target: AnnotationTarget, body: string): Promise<boolean> {
    const existing = noteOf(target)
    if (body.trim() === '') return existing ? deleteNote(existing.id) : true
    return existing ? updateNote(existing, body) : addNote(target, body)
  }

  return {
    analysisId,
    tags,
    notes,
    loading,
    loadError,
    ensureLoaded,
    reload,
    tagsOf,
    noteOf,
    addTag,
    removeTag,
    saveNote,
    deleteNote,
  }
})
