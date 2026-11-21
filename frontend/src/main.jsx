import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'
import './additions.css'
import './theme.css'
import './life/life.css'
import './tokens.css'
import './design.css'
import './assistant.css'
import InstallPrompt from './InstallPrompt'
import OfflineNotice from './OfflineNotice'
import './install-prompt.css'
import './offline-notice.css'

// Installable + offline shell in the built app; the dev server stays untouched.
// `updateViaCache: none` makes the browser revalidate sw.js itself, so a new
// SHELL version is picked up on the next visit rather than from HTTP cache.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' }).catch(() => { });
    });
}
createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>)

// PWA chrome lives outside <App /> so a crash inside the app cannot take the
// install path or the connectivity notice down with it.
const pwaHost = document.createElement('div')
pwaHost.id = 'pwa-banners-root'
document.body.appendChild(pwaHost)
createRoot(pwaHost).render(<><InstallPrompt /><OfflineNotice /></>)
