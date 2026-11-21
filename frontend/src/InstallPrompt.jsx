import React, { useEffect, useState } from 'react';
import './install-prompt.css';

/**
 * Android/Chrome install banner.
 *
 * Chrome fires `beforeinstallprompt` only when the app meets the installability
 * criteria (HTTPS, manifest with 192+512 icons, a service worker with a fetch
 * handler). Suppressing the event lets the app show its own prompt instead of
 * the mini-infobar, and `prompt()` must be called from a user gesture — hence
 * the explicit Install button.
 *
 * Shown at most once: dismissing it is remembered, and it is never rendered in
 * standalone (already installed) mode or in browsers that cannot install.
 */
const DISMISSED_KEY = 'nirvaah.install.dismissed';

export default function InstallPrompt() {
    const [deferred, setDeferred] = useState(null);
    const [visible, setVisible] = useState(false);

    useEffect(() => {
        const standalone =
            window.matchMedia('(display-mode: standalone)').matches ||
            window.navigator.standalone === true;
        // iOS gets a different flow (Share -> Add to Home Screen), which this
        // banner cannot trigger, so it stays hidden there.
        const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);

        if (standalone || isIos || localStorage.getItem(DISMISSED_KEY) === '1') return undefined;

        const onPrompt = (event) => {
            // Always suppress Chrome's mini-infobar, but never bring our own
            // banner back after the user has dismissed it.
            event.preventDefault();
            if (localStorage.getItem(DISMISSED_KEY) === '1') return;
            setDeferred(event);
            setVisible(true);
        };
        const onInstalled = () => {
            setVisible(false);
            setDeferred(null);
            localStorage.setItem(DISMISSED_KEY, '1');
        };

        window.addEventListener('beforeinstallprompt', onPrompt);
        window.addEventListener('appinstalled', onInstalled);
        return () => {
            window.removeEventListener('beforeinstallprompt', onPrompt);
            window.removeEventListener('appinstalled', onInstalled);
        };
    }, []);

    // Lets the layout reserve bottom space only while the fixed banner is on
    // screen, instead of leaving a permanent gap on every page.
    useEffect(() => {
        document.body.classList.toggle('has-install-prompt', visible);
        return () => document.body.classList.remove('has-install-prompt');
    }, [visible]);

    if (!visible) return null;

    const install = async () => {
        if (!deferred) return;
        try {
            await deferred.prompt();
            const choice = await deferred.userChoice;
            if (choice?.outcome !== 'accepted') {
                localStorage.setItem(DISMISSED_KEY, '1');
            }
        } catch {
            // The prompt can only be used once; a failure is not worth a crash.
            localStorage.setItem(DISMISSED_KEY, '1');
        } finally {
            setDeferred(null);
            setVisible(false);
        }
    };

    const dismiss = () => {
        setVisible(false);
        localStorage.setItem(DISMISSED_KEY, '1');
    };

    return (
        <div className="install-prompt" role="dialog" aria-label="Install Nirvaah">
            <img className="install-prompt-icon" src="/icon-192.png" alt="" width="44" height="44" />
            <div className="install-prompt-text">
                <strong>Install Nirvaah</strong>
                <span>Full screen, opens like an app.</span>
            </div>
            <button type="button" className="install-prompt-go" onClick={install}>Install</button>
            <button type="button" className="install-prompt-close" onClick={dismiss} aria-label="Not now">
                {'\u00D7'}
            </button>
        </div>
    );
}
