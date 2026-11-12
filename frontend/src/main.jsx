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

// Installable + offline shell in the built app; the dev server stays untouched.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').catch(() => { });
    });
}
createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>)
