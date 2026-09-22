import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { LocaleProvider } from './lib/locale'
import './styles/base.css'
import './styles/layout.css'
import './styles/components.css'
import './styles/context-sources.css'
import './styles/conversation.css'
import './styles/inspector.css'
import './styles/onboarding.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LocaleProvider>
      <App />
    </LocaleProvider>
  </StrictMode>,
)
