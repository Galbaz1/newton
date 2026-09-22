import { ExternalLink } from 'lucide-react'
import type { OnboardingProfile } from '../../api/types'
import { Badge, Notice } from '../../components/ui'
import { formatDateTime } from '../../lib/format'
import { useLocale } from '../../lib/locale'

/** Only http(s) links from the server are rendered as anchors. */
export function safeExternalUrl(url: string): string | null {
  return /^https?:\/\//i.test(url) ? url : null
}

function TagList({ title, values }: { title: string; values: string[] | undefined }) {
  if (!values || values.length === 0) return null
  return (
    <div className="profile-block">
      <h3>{title}</h3>
      <ul className="tag-list">
        {values.map((value) => (
          <li key={value} className="tag">
            {value}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Research profile: overview, activities, roles, terminology and cited claims. */
export function RunProfile({ profile }: { profile: OnboardingProfile }) {
  const { text } = useLocale()
  const empty =
    !profile.overview &&
    !profile.activities?.length &&
    !profile.roles?.length &&
    !profile.terminology?.length &&
    !profile.claims?.length &&
    !profile.limitations?.length
  return (
    <section className="run-section" aria-label={text({ en: 'Company profile', nl: 'Bedrijfsprofiel' })}>
      <h2>{text({ en: 'Company profile', nl: 'Bedrijfsprofiel' })}</h2>
      <p className="row wrap">
        <Badge tone="missing">
          {profile.authority === 'public_research_synthesis' || !profile.authority
            ? text({ en: 'Research summary from public sources', nl: 'Onderzoekssynthese uit openbare bronnen' })
            : `${text({ en: 'Authority:', nl: 'Autoriteit:' })} ${profile.authority}`}
        </Badge>
        {profile.identity_uncertain && <Badge tone="error">{text({ en: 'Company identity uncertain', nl: 'Bedrijfsidentiteit onzeker' })}</Badge>}
      </p>
      <p className="small muted">
        {text({ en: 'Claims link to their source.', nl: 'Claims linken naar hun bron.' })}
      </p>
      {profile.identity_uncertain && (
        <Notice tone="warning">
          {text({ en: 'Review the sources before relying on these claims.', nl: 'Controleer de bronnen voordat je op deze claims vertrouwt.' })}
        </Notice>
      )}
      {profile.limitations && profile.limitations.length > 0 && (
        <div className="profile-block">
          <h3>{text({ en: 'Research limitations', nl: 'Beperkingen van het onderzoek' })}</h3>
          <ul className="limitation-list">
            {profile.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </div>
      )}
      {empty && <p className="muted small">{text({ en: 'No profile yet.', nl: 'Nog geen profiel.' })}</p>}
      {profile.overview && <p className="profile-overview">{profile.overview}</p>}
      <TagList title={text({ en: 'Activities', nl: 'Activiteiten' })} values={profile.activities} />
      <TagList title={text({ en: 'Roles', nl: 'Rollen' })} values={profile.roles} />
      <TagList title={text({ en: 'Terminology', nl: 'Terminologie' })} values={profile.terminology} />
      {profile.claims && profile.claims.length > 0 && (
        <div className="profile-block">
          <h3>{text({ en: 'Sources', nl: 'Onderbouwing' })} ({profile.claims.length})</h3>
          <ul className="claim-list">
            {profile.claims.map((claim, index) => {
              const href = safeExternalUrl(claim.url)
              return (
                <li key={`${claim.url}:${index}`} className="claim">
                  <p>{claim.text}</p>
                  <p className="meta">
                    {href ? (
                      <a href={href} target="_blank" rel="noopener noreferrer">
                        {claim.title || claim.url} <ExternalLink size={12} aria-hidden="true" />
                      </a>
                    ) : (
                      <span title={claim.url}>{claim.title || claim.url}</span>
                    )}{' '}
                    · {text({ en: 'retrieved', nl: 'opgehaald' })} {formatDateTime(claim.retrieved_at)}
                  </p>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </section>
  )
}
