/** One function per contract endpoint. Add new endpoints here, types in types.ts. */
import { apiUrl, del, get, requestUrl, sendForm, sendJson } from './http'
import type {
  Company,
  Health,
  Investigation,
  Machine,
  MachineInput,
  Message,
  OnboardingInput,
  OnboardingRun,
  Page,
  Readiness,
  QuestionInput,
  Series,
  SeriesMapping,
  SeriesQuery,
  Source,
  SourceAnnotations,
  User,
} from './types'

const id = encodeURIComponent

/** Builds `?channel=..&start=..&end=..`, omitting blank values. */
function seriesQuery(query: SeriesQuery | undefined): string {
  const params = new URLSearchParams()
  for (const key of ['channel', 'start', 'end'] as const) {
    const value = query?.[key]?.trim()
    if (value) params.set(key, value)
  }
  const encoded = params.toString()
  return encoded ? `?${encoded}` : ''
}

export const api = {
  health: (signal?: AbortSignal) => get<Health>('/health', signal),

  register: (email: string, password: string) =>
    sendJson<User>('POST', '/auth/register', { email, password }),
  login: (email: string, password: string) =>
    sendJson<User>('POST', '/auth/login', { email, password }),
  logout: () => sendJson<{ ok: boolean }>('POST', '/auth/logout'),
  me: () => get<User>('/auth/me'),

  companies: () => get<Company[]>('/companies'),
  createCompany: (name: string, description: string) =>
    sendJson<Company>('POST', '/companies', { name, description }),

  machines: (companyId: string) => get<Machine[]>(`/companies/${id(companyId)}/machines`),
  createMachine: (companyId: string, input: MachineInput) =>
    sendJson<Machine>('POST', `/companies/${id(companyId)}/machines`, input),
  machine: (machineId: string) => get<Machine>(`/machines/${id(machineId)}`),
  updateMachine: (machineId: string, patch: Partial<MachineInput>) =>
    sendJson<Machine>('PATCH', `/machines/${id(machineId)}`, patch),
  readiness: (machineId: string) => get<Readiness>(`/machines/${id(machineId)}/readiness`),

  sources: (machineId: string) => get<Source[]>(`/machines/${id(machineId)}/sources`),
  uploadSource: (machineId: string, file: File, revision: string) => {
    const form = new FormData()
    form.append('file', file)
    if (revision.trim()) form.append('revision', revision.trim())
    return sendForm<Source>(`/machines/${id(machineId)}/sources`, form)
  },
  updateSource: (sourceId: string, patch: { revision?: string; mapping?: SeriesMapping }) =>
    sendJson<Source>('PATCH', `/sources/${id(sourceId)}`, patch),
  deleteSource: (sourceId: string) => del<{ ok: boolean }>(`/sources/${id(sourceId)}`),
  pages: (sourceId: string, signal?: AbortSignal) =>
    get<Page[]>(`/sources/${id(sourceId)}/pages`, signal),
  series: (sourceId: string, signal?: AbortSignal, query?: SeriesQuery) =>
    get<Series>(`/sources/${id(sourceId)}/series${seriesQuery(query)}`, signal),
  /** Parsed annotation intervals and provenance for annotation sources. */
  annotations: (sourceId: string, signal?: AbortSignal) =>
    get<SourceAnnotations>(`/sources/${id(sourceId)}/annotations`, signal),
  /** Every source of the company, including the machine-less company library. */
  companySources: (companyId: string) => get<Source[]>(`/companies/${id(companyId)}/sources`),
  /** Evidence carries a server-provided series URL; it is validated as /api. */
  seriesByUrl: (url: string, signal?: AbortSignal) => requestUrl<Series>(url, { signal }),

  investigations: (machineId: string) =>
    get<Investigation[]>(`/machines/${id(machineId)}/investigations`),
  createInvestigation: (machineId: string, title?: string) =>
    sendJson<Investigation>('POST', '/investigations', {
      machine_id: machineId,
      ...(title?.trim() ? { title: title.trim() } : {}),
    }),
  investigation: (investigationId: string) =>
    get<Investigation>(`/investigations/${id(investigationId)}`),
  /** `measurement` is only sent when the user chose a scope; default stays whole-file. */
  sendMessage: (investigationId: string, body: QuestionInput) => sendJson<Message>('POST', `/investigations/${id(investigationId)}/messages`, body),
  sendCorrection: (
    investigationId: string,
    body: { text: string; expected_context_version: number },
  ) => sendJson<Investigation>('POST', `/investigations/${id(investigationId)}/corrections`, body),

  onboardingRuns: (companyId: string) =>
    get<OnboardingRun[]>(`/companies/${id(companyId)}/onboarding`),
  createOnboarding: (companyId: string, input: OnboardingInput) =>
    sendJson<OnboardingRun>('POST', `/companies/${id(companyId)}/onboarding`, input),
  onboarding: (runId: string, signal?: AbortSignal) =>
    get<OnboardingRun>(`/onboarding/${id(runId)}`, signal),
  /** One file per request; returns the complete updated run. */
  uploadOnboardingFile: (runId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return sendForm<OnboardingRun>(`/onboarding/${id(runId)}/files`, form)
  },
  startOnboarding: (runId: string) => sendJson<OnboardingRun>('POST', `/onboarding/${id(runId)}/start`, {}),
  pauseOnboarding: (runId: string) => sendJson<OnboardingRun>('POST', `/onboarding/${id(runId)}/pause`, {}),
  resumeOnboarding: (runId: string) => sendJson<OnboardingRun>('POST', `/onboarding/${id(runId)}/resume`, {}),
  answerOnboarding: (runId: string, questionId: string, answer: string) =>
    sendJson<OnboardingRun>('POST', `/onboarding/${id(runId)}/answers`, { question_id: questionId, answer }),
}

/** URLs for binary resources rendered directly by the browser. */
export const resourceUrl = {
  original: (sourceId: string) => apiUrl(`/sources/${id(sourceId)}/original`),
  pageImage: (sourceId: string, page: number) =>
    apiUrl(`/sources/${id(sourceId)}/pages/${page}/image`),
}
