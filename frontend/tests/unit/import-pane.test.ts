import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisCreated } from '@/api'
import { ImportUploadError } from '@/composables/use-import-upload'

vi.mock('@/composables/use-import-upload', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  const { ref } = await import('vue')
  const state = { progress: ref(0), uploading: ref(false), upload: vi.fn() }
  return { ...actual, useImportUpload: () => state, importUploadState: state }
})

const { importUploadState: importUpload } = await import('@/composables/use-import-upload') as unknown as {
  importUploadState: { progress: { value: number }; uploading: { value: boolean }; upload: ReturnType<typeof vi.fn> }
}

const ImportPane = (await import('@/components/ImportPane.vue')).default

const CREATED = { id: 11, filename: 'trace.pcap', status: 'queued', warnings: [] } as unknown as AnalysisCreated
const PCAP_HEAD = [0xd4, 0xc3, 0xb2, 0xa1, 2, 0, 4, 0]
const ELF_HEAD = [0x7f, 0x45, 0x4c, 0x46, 2, 1, 1, 0]
const MIB = 1024 ** 2
const GIB = 1024 ** 3

function fileWith(head: number[], name: string, size?: number): File {
  const file = new File([Uint8Array.from(head)], name)
  if (size !== undefined) Object.defineProperty(file, 'size', { value: size })
  return file
}

function mountPane() {
  const wrapper = mount(ImportPane, { global: { plugins: [Quasar] } })
  return wrapper
}

async function chooseFile(wrapper: VueWrapper, file: File) {
  const input = wrapper.find('.import-file-input')
  Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
  await input.trigger('change')
  await flushPromises()
}

function importButton(wrapper: VueWrapper) {
  return wrapper.find('.import-btn')
}

function errorText(wrapper: VueWrapper): string {
  return wrapper.find('.import-error').text()
}

describe('ImportPane', () => {
  beforeEach(() => {
    importUpload.progress.value = 0
    importUpload.uploading.value = false
    importUpload.upload.mockReset()
    importUpload.upload.mockResolvedValue(CREATED)
  })

  it('shows a PCAP capture and imports it through the capture path', async () => {
    const wrapper = mountPane()
    const file = fileWith(PCAP_HEAD, 'trace.pcap', 1024)
    await chooseFile(wrapper, file)

    expect(wrapper.find('.import-kind').text()).toBe('PCAP capture')
    expect(importButton(wrapper).attributes('disabled')).toBeUndefined()
    await importButton(wrapper).trigger('click')
    await flushPromises()
    expect(importUpload.upload).toHaveBeenCalledWith(file, 'pcap')
  })

  it('shows a memory image with the Windows note and imports it as a memory image', async () => {
    const wrapper = mountPane()
    const file = fileWith(ELF_HEAD, 'core.elf', 1024)
    await chooseFile(wrapper, file)

    expect(wrapper.find('.import-kind').text()).toBe('Memory image')
    expect(wrapper.find('.import-memory-note').text()).toContain('Windows 10 and 11')
    await importButton(wrapper).trigger('click')
    await flushPromises()
    expect(importUpload.upload).toHaveBeenCalledWith(file, 'memory_image')
  })

  it('shows an inline error and disables the button for an unsupported file', async () => {
    const wrapper = mountPane()
    await chooseFile(wrapper, fileWith([0x50, 0x4b, 0x03, 0x04], 'archive.zip', 10))

    expect(errorText(wrapper)).toBe('Not a PCAP capture or a memory image')
    expect(importButton(wrapper).attributes('disabled')).toBeDefined()
    expect(importUpload.upload).not.toHaveBeenCalled()
  })

  it('refuses a memory image over 5 GB before any upload', async () => {
    const wrapper = mountPane()
    await chooseFile(wrapper, fileWith(ELF_HEAD, 'huge.elf', 5 * GIB + 1))

    expect(errorText(wrapper)).toContain('5 GB')
    expect(importButton(wrapper).attributes('disabled')).toBeDefined()
  })

  it('refuses a PCAP over 512 MB, but accepts one at the limit', async () => {
    const wrapper = mountPane()
    await chooseFile(wrapper, fileWith(PCAP_HEAD, 'big.pcap', 512 * MIB + 1))
    expect(errorText(wrapper)).toContain('512 MB')
    expect(importButton(wrapper).attributes('disabled')).toBeDefined()

    await chooseFile(wrapper, fileWith(PCAP_HEAD, 'edge.pcap', 512 * MIB))
    expect(wrapper.find('.import-error').exists()).toBe(false)
    expect(importButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it.each([
    ['too_large', 'The backend refused the file: it is over the size limit.'],
    ['unsupported', 'The backend does not accept this file type.'],
    ['network', 'Could not reach the backend.'],
  ] as const)('maps a %s failure to its message', async (failure, message) => {
    importUpload.upload.mockRejectedValue(new ImportUploadError(failure, 'raw'))
    const wrapper = mountPane()
    await chooseFile(wrapper, fileWith(PCAP_HEAD, 'trace.pcap', 1024))
    await importButton(wrapper).trigger('click')
    await flushPromises()
    expect(errorText(wrapper)).toBe(message)
  })

  it('shows the backend message for any other failure', async () => {
    importUpload.upload.mockRejectedValue(new ImportUploadError('failed', 'disk full'))
    const wrapper = mountPane()
    await chooseFile(wrapper, fileWith(PCAP_HEAD, 'trace.pcap', 1024))
    await importButton(wrapper).trigger('click')
    await flushPromises()
    expect(errorText(wrapper)).toBe('disk full')
  })

  it('emits the created analysis once the upload succeeds', async () => {
    const wrapper = mountPane()
    await chooseFile(wrapper, fileWith(PCAP_HEAD, 'trace.pcap', 1024))
    await importButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.emitted('imported')).toEqual([[CREATED]])
  })

  it('shows progress and disables the button while uploading', async () => {
    const wrapper = mountPane()
    await chooseFile(wrapper, fileWith(PCAP_HEAD, 'trace.pcap', 1024))
    importUpload.uploading.value = true
    importUpload.progress.value = 0.4
    await flushPromises()

    expect(wrapper.find('.import-progress').text()).toBe('Uploading 40%')
    expect(importButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.emitted('busy')?.at(-1)).toEqual([true])
  })

  it('lists the size limits of both kinds', () => {
    const wrapper = mountPane()
    expect(wrapper.find('.import-limits').text()).toContain('512 MB')
    expect(wrapper.find('.import-limits').text()).toContain('5 GB')
  })
})
