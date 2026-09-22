import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api/client'
import { errorMessage } from '../../api/http'
import type { OnboardingRun, PendingQuestion } from '../../api/types'
import { Button, Notice } from '../../components/ui'
import { useLocale } from '../../lib/locale'

interface Props {
  runId: string
  questions: PendingQuestion[]
  onAnswered: (run: OnboardingRun) => void
}

/** Owner clarifications. Answering records only; the owner resumes explicitly. */
export function Clarifications({ runId, questions, onAnswered }: Props) {
  const { text } = useLocale()
  return (
    <section className="run-section" aria-label={text({ en: 'Open questions', nl: 'Openstaande vragen' })}>
      <h2>{text({ en: 'Questions for you', nl: 'Vragen aan u' })} ({questions.length})</h2>
      {questions.length === 0 && <p className="muted small">{text({ en: 'No open questions.', nl: 'Geen openstaande vragen.' })}</p>}
      {questions.length > 0 && (
        <p className="small muted">
          {text({ en: 'Save an answer, then resume the run when ready.', nl: 'Sla een antwoord op en hervat de run wanneer je klaar bent.' })}
        </p>
      )}
      <ul className="card-list">
        {questions.map((question) => (
          <ClarificationCard key={question.id} runId={runId} question={question} onAnswered={onAnswered} />
        ))}
      </ul>
    </section>
  )
}

function ClarificationCard({
  runId,
  question,
  onAnswered,
}: {
  runId: string
  question: PendingQuestion
  onAnswered: (run: OnboardingRun) => void
}) {
  const { text } = useLocale()
  const [answer, setAnswer] = useState(question.answer ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const answered = Boolean(question.answer)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!answer.trim()) return
    setBusy(true)
    setError(null)
    try {
      onAnswered(await api.answerOnboarding(runId, question.id, answer.trim()))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className={`card card-${answered ? 'ready' : 'missing'}`}>
      <p className="clarification-question">{question.question}</p>
      {question.reason && <p className="meta">{question.reason}</p>}
      {question.source_ids.length > 0 && (
        <p className="meta">{text({ en: 'Applies to', nl: 'Betreft' })} {question.source_ids.length} {text({ en: 'source(s)', nl: 'bron(nen)' })}</p>
      )}
      {answered && <p className="small">{text({ en: 'Answer:', nl: 'Antwoord:' })} {question.answer}</p>}
      <form className="stack" onSubmit={submit}>
        <textarea
          aria-label={text({ en: `Answer: ${question.question}`, nl: `Antwoord op: ${question.question}` })}
          rows={2}
          maxLength={4000}
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
        />
        {error && <Notice tone="error">{error}</Notice>}
        <div className="row">
          <Button type="submit" variant="primary" busy={busy} disabled={!answer.trim()}>
            {answered ? text({ en: 'Update answer', nl: 'Antwoord bijwerken' }) : text({ en: 'Save answer', nl: 'Antwoord vastleggen' })}
          </Button>
        </div>
      </form>
    </li>
  )
}
