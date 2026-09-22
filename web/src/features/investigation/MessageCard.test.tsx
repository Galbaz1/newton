import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import type { Message } from '../../api/types'
import { MessageCard } from './MessageCard'

const message: Message = {
  id: 'synthetic-answer', role: 'assistant', text: 'Earlier context answer.',
  created_at: '2026-09-21T09:00:00Z', scope_revision: 1, context_version: 1,
  status: 'complete', evidence: [], warnings: [],
}

it('immediately marks a cached answer stale when source context changes', () => {
  const html = renderToStaticMarkup(
    <MessageCard message={message} scopeRevision={1} contextVersion={2} onInspect={() => {}} />,
  )
  expect(html).toContain('Superseded by changed context or correction')
  expect(html).toContain('message-superseded')
})

it('keeps a current answer and historical user message separate from stale answers', () => {
  const current = renderToStaticMarkup(
    <MessageCard message={message} scopeRevision={1} contextVersion={1} onInspect={() => {}} />,
  )
  const user = renderToStaticMarkup(
    <MessageCard message={{ ...message, role: 'user' }} scopeRevision={2} contextVersion={2} onInspect={() => {}} />,
  )
  expect(current).not.toContain('Superseded by')
  expect(user).not.toContain('Superseded by')
})
