import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, resourceUrl } from '../../api/client'
import { Button, Notice, Spinner } from '../../components/ui'
import { useResource } from '../../lib/useResource'

/** Page image (when the server has one) next to the extracted text. */
export function PageViewer({ sourceId, initialPage }: { sourceId: string; initialPage: number | null }) {
  const pages = useResource(`pages:${sourceId}`, (signal) => api.pages(sourceId, signal))
  const [number, setNumber] = useState(initialPage ?? 1)
  const [imageFailed, setImageFailed] = useState(false)

  useEffect(() => setNumber(initialPage ?? 1), [sourceId, initialPage])
  useEffect(() => setImageFailed(false), [sourceId, number])

  if (pages.error) {
    return (
      <Notice tone="error" onRetry={() => void pages.reload()}>
        {pages.error}
      </Notice>
    )
  }
  if (!pages.data) return <Spinner label="Loading pages…" />

  const numbers = pages.data.map((page) => page.number)
  const last = numbers.length ? Math.max(...numbers) : 1
  const page = pages.data.find((item) => item.number === number)

  return (
    <div className="pages">
      <div className="row pager">
        <Button onClick={() => setNumber(number - 1)} disabled={number <= 1} aria-label="Previous page">
          <ChevronLeft size={14} aria-hidden="true" />
        </Button>
        <span className="meta">
          Page {number} of {last}
        </span>
        <Button onClick={() => setNumber(number + 1)} disabled={number >= last} aria-label="Next page">
          <ChevronRight size={14} aria-hidden="true" />
        </Button>
      </div>
      {imageFailed ? (
        <Notice tone="info">No page image is available for this source (text-only original).</Notice>
      ) : (
        <img
          className="page-image"
          src={resourceUrl.pageImage(sourceId, number)}
          alt={`Original page ${number}`}
          loading="lazy"
          onError={() => setImageFailed(true)}
        />
      )}
      <h4>Extracted text</h4>
      {page?.text.trim() ? (
        <pre className="page-text">{page.text}</pre>
      ) : (
        <p className="muted small">
          No embedded text is available for this page. Inspect the original image above;
          model observations are separate from the source.
        </p>
      )}
    </div>
  )
}
