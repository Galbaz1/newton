import { FolderOpen, MessagesSquare, SlidersHorizontal } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from './api/client'
import type { User } from './api/types'
import { AppHeader } from './components/AppHeader'
import { EmptyState, Notice, Spinner } from './components/ui'
import { CompanySection } from './features/context/CompanySection'
import { InvestigationSection } from './features/context/InvestigationSection'
import { MachineSection } from './features/context/MachineSection'
import { ReadinessSection } from './features/context/ReadinessSection'
import { InspectorPanel } from './features/evidence/InspectorPanel'
import { targetFromEvidence, targetFromSource } from './features/evidence/inspectTarget'
import type { InspectTarget } from './features/evidence/inspectTarget'
import { InvestigationView } from './features/investigation/InvestigationView'
import { OnboardingRunView } from './features/onboarding/OnboardingRunView'
import { OnboardingSection } from './features/onboarding/OnboardingSection'
import { OnboardingStart } from './features/onboarding/OnboardingStart'
import { useOnboardingRun } from './features/onboarding/useOnboardingRun'
import { SourcesPanel } from './features/sources/SourcesPanel'
import { useResource } from './lib/useResource'
import type { OnboardingQuestion } from './api/types'
import { scopeForInvestigation, scopeFromQuestion } from './features/investigation/MeasurementScope'
import type { ScopeDraft } from './features/investigation/MeasurementScope'
import { useLocale } from './lib/locale'

type Pane = 'context' | 'conversation' | 'sources'
/** What the main pane shows: the investigation, the onboarding form or one run. */
type View = { kind: 'investigation' } | { kind: 'onboarding-start' } | { kind: 'onboarding-run'; runId: string }

/**
 * Signed-in shell. Owns the selection (company → machine → investigation) and
 * the server resources derived from it; features receive data and callbacks.
 */
export function Workspace({ user, onSignedOut }: { user: User; onSignedOut: () => void }) {
  const { text } = useLocale()
  const panes = [
    { id: 'context' as const, label: text({ en: 'Context', nl: 'Context' }), icon: SlidersHorizontal },
    { id: 'conversation' as const, label: text({ en: 'Investigate', nl: 'Onderzoeken' }), icon: MessagesSquare },
    { id: 'sources' as const, label: text({ en: 'Sources', nl: 'Bronnen' }), icon: FolderOpen },
  ]
  const [companyId, setCompanyId] = useState<string | null>(null)
  const [machineId, setMachineId] = useState<string | null>(null)
  const [investigationId, setInvestigationId] = useState<string | null>(null)
  const [target, setTarget] = useState<InspectTarget | null>(null)
  const [pane, setPane] = useState<Pane>('context')
  const [view, setView] = useState<View>({ kind: 'investigation' })
  // Bound to one investigation id, so another machine/investigation never inherits it.
  const [prefill, setPrefill] = useState<{ investigationId: string; text: string; scope: ScopeDraft | null } | null>(null)

  const health = useResource('health', (signal) => api.health(signal))
  const companies = useResource('companies', () => api.companies())
  const machines = useResource(companyId && `machines:${companyId}`, () => api.machines(companyId!))
  const runs = useResource(companyId && `onboarding-runs:${companyId}`, () => api.onboardingRuns(companyId!))
  const companySources = useResource(companyId && `company-sources:${companyId}`, () =>
    api.companySources(companyId!),
  )
  const runId = view.kind === 'onboarding-run' ? view.runId : null
  const run = useOnboardingRun(runId, () => refreshAfterRun())
  const machine = useResource(machineId && `machine:${machineId}`, () => api.machine(machineId!))
  const sources = useResource(machineId && `sources:${machineId}`, () => api.sources(machineId!))
  const readiness = useResource(machineId && `ready:${machineId}`, () => api.readiness(machineId!))
  const investigations = useResource(machineId && `inv:${machineId}`, () => api.investigations(machineId!))
  const investigation = useResource(investigationId && `investigation:${investigationId}`, () =>
    api.investigation(investigationId!),
  )

  // Default each level to its first entry once loaded; never invent entries.
  useEffect(() => {
    if (!companyId && companies.data?.[0]) setCompanyId(companies.data[0].id)
  }, [companies.data, companyId])
  useEffect(() => {
    const first = machines.data?.find((item) => item.company_id === companyId)
    if (!machineId && first) setMachineId(first.id)
  }, [machines.data, machineId, companyId])
  useEffect(() => {
    const first = investigations.data?.find((item) => item.machine_id === machineId)
    if (!investigationId && first) setInvestigationId(first.id)
  }, [investigations.data, investigationId, machineId])

  function selectCompany(id: string) {
    setCompanyId(id)
    selectMachine(null)
    setView({ kind: 'investigation' })
  }
  /** A run creates machines and sources; every list derived from them is refetched. */
  function refreshAfterRun() {
    void Promise.all([
      machines.reload(), sources.reload(), readiness.reload(), runs.reload(), companySources.reload(),
    ])
  }
  function openRun(id: string) {
    setView({ kind: 'onboarding-run', runId: id })
    setPane('conversation')
  }
  /**
   * Ready starter question: select its machine, create an investigation titled
   * after the question and prefill the text. The user submits it themselves.
   */
  async function openStarterQuestion(question: OnboardingQuestion) {
    if (!question.machine_id) throw new Error(text({ en: 'This starter question is not linked to a machine.', nl: 'Deze startvraag is aan geen machine gekoppeld.' }))
    const created = await api.createInvestigation(question.machine_id, question.text.slice(0, 200))
    selectMachine(question.machine_id)
    setInvestigationId(created.id)
    setPrefill({ investigationId: created.id, text: question.text, scope: scopeFromQuestion(question) })
    setView({ kind: 'investigation' })
    setPane('conversation')
    void investigations.reload()
  }
  function inspectSourceById(sourceId: string) {
    const source =
      companySources.data?.find((item) => item.id === sourceId) ??
      sources.data?.find((item) => item.id === sourceId)
    if (source) inspect(targetFromSource(source))
    else void companySources.reload()
  }
  function selectMachine(id: string | null) {
    setMachineId(id)
    setInvestigationId(null)
    setTarget(null)
  }
  /** Source and context edits bump context_version; refetch everything tied to it. */
  function refreshContext() {
    void Promise.all([
      machine.reload(), machines.reload(), sources.reload(), readiness.reload(), investigation.reload(),
    ])
  }
  function inspect(next: InspectTarget) {
    setTarget(next)
    setPane('sources')
  }
  async function signOut() {
    try {
      await api.logout()
    } finally {
      onSignedOut()
    }
  }

  // Guard against the one render where the previous machine is still in state.
  const current = machine.data?.id === machineId ? machine.data : null

  return (
    <div className="app">
      <AppHeader user={user} health={health.data} healthError={health.error} onSignOut={() => void signOut()} />
      <div className="workspace" data-pane={pane}>
        <aside className="pane pane-context" aria-label="Company and machine context">
          {companies.error && (
            <Notice tone="error" onRetry={() => void companies.reload()}>
              {companies.error}
            </Notice>
          )}
          {!companies.data && companies.loading && <Spinner label={text({ en: 'Loading companies…', nl: 'Bedrijven laden…' })} />}
          {companies.data && (
            <CompanySection
              companies={companies.data}
              selectedId={companyId}
              onSelect={selectCompany}
              onCreated={(company) => {
                void companies.reload()
                selectCompany(company.id)
              }}
            />
          )}
          {companies.data && (
            <OnboardingSection
              runs={companyId ? runs.data : []}
              loading={runs.loading}
              error={runs.error}
              selectedId={runId}
              onSelect={openRun}
              onNew={() => {
                setView({ kind: 'onboarding-start' })
                setPane('conversation')
              }}
              onRetry={() => void runs.reload()}
            />
          )}
          {companyId && machines.error && (
            <Notice tone="error" onRetry={() => void machines.reload()}>
              {machines.error}
            </Notice>
          )}
          {companyId && machines.data && (
            <MachineSection
              companyId={companyId}
              machines={machines.data}
              selected={current}
              onSelect={selectMachine}
              onSaved={(saved) => {
                if (saved.id !== machineId) selectMachine(saved.id)
                machine.setData(saved)
                void Promise.all([machines.reload(), readiness.reload()])
              }}
            />
          )}
          {machineId && (
            <ReadinessSection
              readiness={readiness.data}
              loading={readiness.loading}
              error={readiness.error}
              onRetry={() => void readiness.reload()}
            />
          )}
          {machineId && investigations.data && (
            <InvestigationSection
              machineId={machineId}
              investigations={investigations.data}
              selectedId={investigationId}
              error={investigations.error}
              onSelect={(id) => {
                setInvestigationId(id)
                setView({ kind: 'investigation' })
                setPane('conversation')
              }}
              onCreated={(created) => {
                void investigations.reload()
                setInvestigationId(created.id)
                setView({ kind: 'investigation' })
                setPane('conversation')
              }}
            />
          )}
        </aside>

        <main className="pane pane-conversation">
          {machine.error && (
            <Notice tone="error" onRetry={() => void machine.reload()}>
              {machine.error}
            </Notice>
          )}
          {view.kind === 'onboarding-start' && companies.data && (
            <OnboardingStart
              companies={companies.data}
              companyId={companyId}
              onCompanyCreated={(company) => {
                void companies.reload()
                setCompanyId(company.id)
                selectMachine(null)
              }}
              onOpened={(created) => {
                if (created.company_id !== companyId) setCompanyId(created.company_id)
                openRun(created.id)
              }}
              onCancel={() => setView({ kind: 'investigation' })}
            />
          )}
          {view.kind === 'onboarding-run' && (
            <OnboardingRunView
              key={view.runId}
              run={run}
              companyName={companies.data?.find((company) => company.id === companyId)?.name ?? null}
              onOpenQuestion={openStarterQuestion}
              onInspectSource={inspectSourceById}
            />
          )}
          {view.kind === 'investigation' && !machineId && (
            <EmptyState
              title={text({ en: 'Start with a company and a machine', nl: 'Begin met een bedrijf en een machine' })}
              action={
                <button type="button" className="btn btn-primary" onClick={() => setView({ kind: 'onboarding-start' })}>
                  {text({ en: 'Onboard company', nl: 'Bedrijf onboarden' })}
                </button>
              }
            >
              {text({ en: 'Create a company, add a machine, then upload its sources.', nl: 'Maak een bedrijf, voeg een machine toe en upload de bronnen.' })}
            </EmptyState>
          )}
          {view.kind === 'investigation' && current && !investigationId && (
            <EmptyState title={text({ en: `No investigation open for ${current.name}`, nl: `Geen onderzoek open voor ${current.name}` })}>
              {text({ en: `Start an investigation from the context panel. ${sources.data?.length ?? 0} source(s) are available for this machine.`, nl: `Start een onderzoek vanuit het contextpaneel. ${sources.data?.length ?? 0} bron(nen) zijn beschikbaar voor deze machine.` })}
            </EmptyState>
          )}
          {view.kind === 'investigation' && current && investigationId &&
            (!investigation.data ||
              (investigation.data.id === investigationId && investigation.data.machine_id === current.id)) && (
            <InvestigationView
              key={investigationId}
              machine={current}
              investigation={investigation}
              providers={health.data?.providers ?? null}
              providersError={health.error}
              initialDraft={prefill?.investigationId === investigationId ? prefill.text : undefined}
              initialScope={scopeForInvestigation(prefill, investigationId)}
              sources={sources.data}
              onInspectEvidence={(evidence, label) => inspect(targetFromEvidence(evidence, label))}
              onContextStale={refreshContext}
              onRunSettled={() => void health.reload()}
            />
          )}
        </main>

        <aside className="pane pane-sources" aria-label={text({ en: 'Sources and evidence', nl: 'Bronnen en bewijs' })}>
          {target ? (
            <InspectorPanel
              target={target}
              sources={view.kind === 'onboarding-run' ? companySources.data : sources.data}
              onClose={() => setTarget(null)}
            />
          ) : machineId ? (
            <SourcesPanel
              machineId={machineId}
              sources={sources.data}
              loading={sources.loading}
              error={sources.error}
              onInspect={(source) => inspect(targetFromSource(source))}
              onChanged={refreshContext}
            />
          ) : (
            <EmptyState title={text({ en: 'Sources appear here', nl: 'Bronnen verschijnen hier' })}>
              {text({ en: 'Select or add a machine to upload manuals, images, records and time series.', nl: 'Selecteer of voeg een machine toe om handleidingen, afbeeldingen, registraties en tijdreeksen te uploaden.' })}
            </EmptyState>
          )}
        </aside>
      </div>

      <nav className="pane-tabs" aria-label="Workspace panes">
        {panes.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            className={pane === id ? 'pane-tab pane-tab-active' : 'pane-tab'}
            aria-current={pane === id ? 'page' : undefined}
            onClick={() => setPane(id)}
          >
            <Icon size={18} aria-hidden="true" />
            {label}
          </button>
        ))}
      </nav>
    </div>
  )
}
