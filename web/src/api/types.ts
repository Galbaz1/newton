/**
 * Typed mirror of the Newton HTTP contract (/api/openapi.json).
 * IDs are strings and timestamps are ISO 8601 strings.
 */

export interface User {
  id: string
  email: string
}

export interface ProviderInfo {
  id: string
  label: string
  available: boolean
}

export interface Health {
  status: string
  database: string
  retrieval: string
  providers: ProviderInfo[]
  budget: { ceiling_eur: number; spent_eur: number; reserved_eur: number }
}

export interface Company {
  id: string
  name: string
  description: string
  created_at: string
}

export interface Machine {
  id: string
  company_id: string
  name: string
  manufacturer: string
  model: string
  description: string
  context_version: number
  created_at: string
}

export type MachineInput = Pick<Machine, 'name' | 'manufacturer' | 'model' | 'description'>

export type SourceKind = 'document' | 'image' | 'timeseries' | 'annotation'
export type SourceStatus = 'ready' | 'needs_mapping' | 'needs_text' | 'error' | 'quarantined'
/** Provenance class; automatic normal investigations exclude synthetic/demo. */
export type SourceDataClass = 'original' | 'synthetic' | 'demo' | 'derived'

/** One established measurement channel of a time-series source. */
export interface SourceChannel {
  column: string
  label: string
  unit: string
  /** Where the unit was read from; null when the unit is unsupported/unknown. */
  unit_support?: { item_id: string; page: number; quote: string } | null
}

/** Deterministic profiling finding attached to a source or onboarding item. */
export interface Finding {
  code: string
  severity: string
  message: string
}

export interface SeriesMapping {
  time_column: string
  value_column: string
  unit: string
  /** IANA zone; required by the backend when timestamps are naive. */
  timezone?: string | null
}

export interface SourceMetadata {
  page_count?: number
  columns?: string[]
  sample_rows?: unknown[]
  warnings?: string[]
  error?: string
  /** Established channels, when profiling could determine them. */
  channels?: SourceChannel[]
  profile?: Record<string, unknown>
  findings?: Finding[]
  /** Defaults to absolute when omitted. */
  time_basis?: 'absolute' | 'source_local'
  /** Onboarding provenance; `reason` explains quarantine when set. */
  onboarding?: { reason?: string; [key: string]: unknown }
  /** Reader-facing caveats about what this source can and cannot evidence. */
  evidence_caveats?: string[]
  [key: string]: unknown
}

export interface Source {
  id: string
  company_id: string
  /** Null means company library: available to every machine of the company. */
  machine_id: string | null
  filename: string
  media_type: string
  sha256: string
  kind: SourceKind
  status: SourceStatus
  data_class?: SourceDataClass
  revision: string
  version: number
  mapping: SeriesMapping | null
  metadata: SourceMetadata
  created_at: string
}

export interface Page {
  id: string
  number: number
  text: string
}

export interface SeriesPoint {
  time: string
  value: number
}

export interface Series {
  source_id: string
  unit: string
  time_column: string
  value_column: string
  points: SeriesPoint[]
  summary: {
    count: number
    min: number | null
    max: number | null
    mean: number | null
    start: string | null
    end: string | null
  }
  truncated: boolean
  /** Defaults to absolute when omitted. Source-local strings carry no offset. */
  time_basis?: 'absolute' | 'source_local'
}

export interface AnnotationInterval {
  task_id: string
  annotation_id: string
  object_ref: string
  label: string
  start: string | null
  end: string | null
  instant: string | null
}

/** GET /sources/{id}/annotations for annotation sources. */
export interface SourceAnnotations {
  source_id: string
  original_sha256: string
  interval_semantics: 'source_unspecified' | (string & {})
  intervals: AnnotationInterval[]
  findings: Finding[]
}

/** Optional deterministic evidence constraint sent with a question. */
export interface MeasurementScope {
  source_id: string
  channel: string
  start?: string
  end?: string
}

export interface QuestionInput {
  text: string
  model: string
  expected_context_version: number
  measurement?: MeasurementScope
}

export interface Evidence {
  id: string
  source_id: string
  filename: string
  page?: number | null
  excerpt: string
  revision: string
  source_version: number
  kind: SourceKind
  original_url: string
  page_image_url?: string | null
  series_url?: string | null
  original_sha256?: string
  render_sha256?: string
  render_version?: string
  model_input?: {
    format: 'application/pdf'
    original_pages: number[]
    sha256: string
    bytes: number
    operation: string
  }
  /** Captured when the answer is produced; never filled from a current source. */
  derivation?:
    | { method: 'page-text-chunk-v1'; page_id: string; offset: number; max_characters: number; trim_whitespace: true }
    | { method: 'csv-all-rows-summary-v1'; mapping: SeriesMapping; row_count: number; visible_row_count: number }
  retrieval?: {
    method: string
    model: string
    revision: string
    distance: number
    score_is_confidence: false
  }
}

export type MessageStatus = 'complete' | 'superseded' | 'error'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  created_at: string
  scope_revision: number
  context_version: number
  status: MessageStatus
  model?: string | null
  evidence: Evidence[]
  usage?: Record<string, unknown> | null
  warnings: string[]
}

export interface Investigation {
  id: string
  machine_id: string
  title: string
  scope_revision: number
  created_at: string
  messages?: Message[]
}

export type CapabilityState = 'ready' | 'missing' | (string & {})

export interface Capability {
  id: string
  label: string
  state: CapabilityState
  reason: string
}

export interface Readiness {
  context_version: number
  capabilities: Capability[]
  source_count: number
}

export type OnboardingStatus =
  | 'draft'
  | 'running'
  | 'paused'
  | 'completed'
  | 'completed_with_warnings'
  | 'error'
export type OnboardingDataClass = 'original' | 'synthetic' | 'demo'

export interface OnboardingClaim {
  text: string
  url: string
  title: string
  retrieved_at: string
}

export interface OnboardingProfile {
  overview?: string
  activities?: string[]
  roles?: string[]
  terminology?: string[]
  claims?: OnboardingClaim[]
  /** What the research could not establish; shown next to the profile. */
  limitations?: string[]
  identity_uncertain?: boolean
  /** Research synthesis, never a confirmed company record. */
  authority?: 'public_research_synthesis' | (string & {})
}

export interface OnboardingItem {
  id: string
  filename: string
  sha256: string
  kind: string
  status: string
  data_class: string
  machine_id: string | null
  source_id: string | null
  profile: Record<string, unknown>
  findings: Finding[]
}

export interface OnboardingEvent {
  at: string
  kind: string
  message: string
  item_id?: string
}

/** Starter question; only `ready` ones can open an investigation. */
export interface OnboardingQuestion {
  id: string
  text: string
  origin: 'role' | 'source'
  state: 'ready' | 'missing'
  machine_id: string | null
  source_ids: string[]
  reason: string
  capability?: 'document_lookup' | 'measurement_summary' | 'missing'
  /** Exact, backend-validated scope for measurement_summary questions. */
  measurement?: QuestionMeasurement
}

/** Bounds are wire values: offset-bearing for absolute, naive for source-local. */
export interface QuestionMeasurement {
  source_id: string
  channel: string
  start?: string | null
  end?: string | null
}

export interface PendingQuestion {
  id: string
  question: string
  reason: string
  source_ids: string[]
  answer?: string
}

export interface OnboardingRun {
  id: string
  company_id: string
  website: string
  data_class: OnboardingDataClass
  status: OnboardingStatus
  stage: string
  summary: string
  created_at: string
  updated_at: string
  profile: OnboardingProfile
  items: OnboardingItem[]
  events: OnboardingEvent[]
  questions: OnboardingQuestion[]
  pending_questions: PendingQuestion[]
  reviews?: {
    model: string
    effort: string
    role: string
    summary: string
    findings: { target_id: string; category: string; severity: string; reason: string; evidence_ids: string[] }[]
  }[]
}

export interface OnboardingInput {
  website?: string
  data_class?: OnboardingDataClass
}

/** Channel and inclusive period selection for GET /sources/{id}/series. */
export interface SeriesQuery {
  channel?: string
  start?: string
  end?: string
}
