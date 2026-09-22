import { describe, expect, it } from 'vitest'
import type { OnboardingRun } from '../../api/types'
import { dataClassBanner, openClarifications, questionReady, runActions, runChanged, statusInfo } from './runStatus'

const base: OnboardingRun = {
  id: 'run', company_id: 'c', website: '', data_class: 'original', status: 'draft', stage: '',
  summary: '', created_at: '2026-09-22T00:00:00Z', updated_at: '2026-09-22T00:00:00Z',
  profile: {}, items: [], events: [], questions: [], pending_questions: [],
}

describe('runActions', () => {
  it('follows the contract: start draft, pause running, resume paused/error, upload when not running', () => {
    expect(runActions('draft')).toMatchObject({ canStart: true, canPause: false, canResume: false, canUpload: true, isActive: false })
    expect(runActions('running')).toMatchObject({ canStart: false, canPause: true, canResume: false, canUpload: false, isActive: true })
    expect(runActions('paused')).toMatchObject({ canResume: true, canUpload: true, isActive: false })
    expect(runActions('error')).toMatchObject({ canResume: true, canPause: false })
    expect(runActions('completed')).toMatchObject({ canStart: false, canPause: false, canResume: false, canUpload: false })
    expect(runActions('completed_with_warnings')).toMatchObject({ canResume: true, canUpload: false })
  })
})

describe('statusInfo', () => {
  it('uses English by default, Dutch when selected, and echoes unknown states', () => {
    expect(statusInfo('paused').label).toBe('Paused')
    expect(statusInfo('paused', 'nl').label).toBe('Gepauzeerd')
    expect(statusInfo('completed_with_warnings').tone).toBe('missing')
    expect(statusInfo('mystery')).toMatchObject({ label: 'mystery', tone: 'neutral' })
  })
})

describe('dataClassBanner', () => {
  it('is persistent and unmistakable for synthetic/demo only', () => {
    expect(dataClassBanner('original')).toBeNull()
    expect(dataClassBanner('synthetic')).toMatch(/^Synthetic data/)
    expect(dataClassBanner('synthetic', 'nl')).toMatch(/^Synthetische gegevens/)
    expect(dataClassBanner('demo')).toMatch(/^Demo data/)
  })
})

describe('questionReady', () => {
  const question = { id: 'q', text: 't', origin: 'role' as const, state: 'ready' as const, machine_id: 'm', source_ids: [], reason: '' }
  it('needs both a ready state and a machine to open an investigation', () => {
    expect(questionReady(question)).toBe(true)
    expect(questionReady({ ...question, state: 'missing' })).toBe(false)
    expect(questionReady({ ...question, machine_id: null })).toBe(false)
  })
})

describe('runChanged / openClarifications', () => {
  it('detects projection changes that require list refreshes', () => {
    expect(runChanged(null, base)).toBe(false)
    expect(runChanged(base, base)).toBe(false)
    expect(runChanged(base, { ...base, updated_at: '2026-09-22T00:00:02Z' })).toBe(true)
    expect(runChanged(base, { ...base, status: 'running' })).toBe(true)
  })
  it('lists only unanswered clarifications', () => {
    const run = {
      ...base,
      pending_questions: [
        { id: 'a', question: 'A?', reason: '', source_ids: [] },
        { id: 'b', question: 'B?', reason: '', source_ids: [], answer: 'yes' },
      ],
    }
    expect(openClarifications(run).map((q) => q.id)).toEqual(['a'])
  })
})
