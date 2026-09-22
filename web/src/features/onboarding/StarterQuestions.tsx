import { MessageSquarePlus } from 'lucide-react'
import type { OnboardingQuestion } from '../../api/types'
import { Badge } from '../../components/ui'
import { questionReady } from './runStatus'
import { useLocale } from '../../lib/locale'
import type { Locale } from '../../lib/locale'

interface Props {
  questions: OnboardingQuestion[]
  /** Selects the question's machine and opens an investigation with the text prefilled. */
  onOpen: (question: OnboardingQuestion) => void
  busyId?: string | null
}

const ORIGIN_LABEL = { role: 'rol', source: 'bron' } as const
const CAPABILITY_LABEL = {
  document_lookup: 'documentopzoeking',
  measurement_summary: 'meetsamenvatting (min/max/gemiddelde/aantal)',
  missing: 'capaciteit ontbreekt',
} as const

/** One-line statement of the exact scope a starter question carries. */
export function questionScopeLine(question: OnboardingQuestion, locale: Locale = 'en'): string | null {
  const m = question.measurement
  if (!m) return null
  const period = m.start || m.end
    ? ` · ${m.start ?? (locale === 'nl' ? 'begin' : 'start')} ${locale === 'nl' ? 't/m' : 'to'} ${m.end ?? (locale === 'nl' ? 'einde' : 'end')} (${locale === 'nl' ? 'inclusief' : 'inclusive'})`
    : ` · ${locale === 'nl' ? 'hele bestand' : 'whole file'}`
  return `${locale === 'nl' ? 'kanaal' : 'channel'} ${m.channel}${period}`
}

/** Starter questions; ready ones are keyboard-activatable buttons. */
export function StarterQuestions({ questions, onOpen, busyId = null }: Props) {
  const { locale, text } = useLocale()
  const origin = locale === 'nl' ? ORIGIN_LABEL : { role: 'role', source: 'source' }
  const capability = locale === 'nl' ? CAPABILITY_LABEL : { document_lookup: 'document lookup', measurement_summary: 'measurement summary', missing: 'capability unavailable' }
  return (
    <section className="run-section" aria-label={text({ en: 'Starter questions', nl: 'Startvragen' })}>
      <h2>{text({ en: 'Starter questions', nl: 'Startvragen' })} ({questions.length})</h2>
      {questions.length === 0 && (
        <p className="muted small">{text({ en: 'No starter questions yet.', nl: 'Nog geen startvragen.' })}</p>
      )}
      <ul className="question-list">
        {questions.map((question) => {
          const ready = questionReady(question)
          return (
            <li key={question.id} className={`question question-${ready ? 'ready' : 'missing'}`}>
              <button
                type="button"
                className="question-button"
                disabled={!ready || busyId === question.id}
                aria-busy={busyId === question.id || undefined}
                aria-describedby={`question-reason-${question.id}`}
                onClick={() => onOpen(question)}
              >
                <MessageSquarePlus size={15} aria-hidden="true" />
                <span className="question-text">{question.text}</span>
                <Badge tone={ready ? 'ready' : 'missing'}>{ready ? text({ en: 'ready', nl: 'gereed' }) : text({ en: 'unavailable', nl: 'ontbreekt' })}</Badge>
              </button>
              <p className="meta" id={`question-reason-${question.id}`}>
                {text({ en: 'via', nl: 'via' })} {origin[question.origin] ?? question.origin}
                {question.capability ? ` · ${capability[question.capability] ?? question.capability}` : ''}
                {questionScopeLine(question, locale) ? ` · ${questionScopeLine(question, locale)}` : ''}
                {question.source_ids.length > 0 ? ` · ${question.source_ids.length} ${text({ en: 'source(s)', nl: 'bron(nen)' })}` : ''}
                {question.reason ? ` · ${question.reason}` : ''}
                {!ready && !question.machine_id ? ` · ${text({ en: 'no machine linked', nl: 'geen machine gekoppeld' })}` : ''}
              </p>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
