import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import type { ReportVariant } from '@/api'
import { downloadReportFile, jobFailureReason, jobFilename, jobFormat } from '@/services/report-job'
import { DEFAULT_REPORT_INCLUDE, type ReportSections } from '@/services/report-request'
import { reportView } from '@/services/report-view'
import { useJobsStore, type ReportRequest } from '@/stores/jobs'

/** The state of the report dialog of one analysis: the form, the job behind it and what the dialog shows of each. */
export function useReportDialog(analysisId: number, initialFormat: ReportVariant) {
  const jobs = useJobsStore()
  const format = ref<ReportVariant>(initialFormat)
  const include = reactive<ReportSections>({ ...DEFAULT_REPORT_INCLUDE })
  const submitting = ref(false)
  const downloading = ref(false)
  const refusal = ref<string>()
  const composing = ref(false)

  const job = computed(() => jobs.reportFor(analysisId))
  const view = computed(() => reportView(job.value, composing.value))
  const failureReason = computed(() => (job.value ? jobFailureReason(job.value) : undefined))
  const filename = computed(() => (job.value ? jobFilename(job.value) : undefined))
  const builtFormat = computed(() => (job.value ? jobFormat(job.value) : undefined) ?? format.value)

  async function submit(request: ReportRequest): Promise<void> {
    submitting.value = true
    refusal.value = undefined
    const message = await jobs.startReport(analysisId, request.format, request.include)
    submitting.value = false
    if (message) refusal.value = message
    else composing.value = false
  }

  const generate = (): Promise<void> => submit({ format: format.value, include: { ...include } })
  const retry = (): Promise<void> => submit(jobs.requestFor(analysisId) ?? { format: format.value, include: { ...include } })

  function startNewReport(): void {
    refusal.value = undefined
    composing.value = true
  }

  async function download(): Promise<void> {
    if (!job.value) return
    downloading.value = true
    await downloadReportFile(job.value)
    downloading.value = false
  }

  watch([format, include], () => (refusal.value = undefined))
  onMounted(() => (jobs.viewing = analysisId))
  onBeforeUnmount(() => (jobs.viewing = undefined))

  return {
    format,
    include,
    submitting,
    downloading,
    refusal,
    job,
    view,
    failureReason,
    filename,
    builtFormat,
    generate,
    retry,
    startNewReport,
    download,
  }
}
