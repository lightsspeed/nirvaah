import React, { useEffect, useState } from 'react';
import './offline-notice.css';

/**
 * Honest connectivity state.
 *
 * The service worker can serve the application shell offline, but every
 * financial feature is server-authoritative. This says so instead of letting a
 * failed save look successful; it does not queue or retry writes.
 */
export default function OfflineNotice() {
    const [offline, setOffline] = useState(
        () => typeof navigator !== 'undefined' && navigator.onLine === false
    );

    useEffect(() => {
        const goOnline = () => setOffline(false);
        const goOffline = () => setOffline(true);
        window.addEventListener('online', goOnline);
        window.addEventListener('offline', goOffline);
        return () => {
            window.removeEventListener('online', goOnline);
            window.removeEventListener('offline', goOffline);
        };
    }, []);

    useEffect(() => {
        document.body.classList.toggle('is-offline', offline);
        return () => document.body.classList.remove('is-offline');
    }, [offline]);

    if (!offline) return null;

    return (
        <div className="offline-notice" role="status" aria-live="polite">
            <span className="offline-dot" aria-hidden="true" />
            <span>
                <strong>Offline.</strong> Cached app only — saving is unavailable until the
                connection returns.
            </span>
        </div>
    );
}
