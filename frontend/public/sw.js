/* Nirvaah service worker.
 *
 * Scope: the application shell and static assets only. The shell opens after a
 * first successful visit and survives a dead zone; money data never does.
 *
 * Deliberately conservative:
 *   - /api/* is never intercepted, so transactions, tasks, journal entries,
 *     notes, user details and AI conversations always come from the server
 *     (or fail loudly when it is unreachable).
 *   - Any request carrying an Authorization header is passed through untouched,
 *     so no token or authenticated response can land in Cache Storage.
 *   - Navigations are network-first, so a new deployment is picked up on the
 *     next load instead of being pinned to an old build.
 *
 * Bump SHELL when the precache list or strategy changes; activate() deletes
 * every other cache.
 */

const SHELL = 'nirvaah-shell-v3';
const SHELL_ASSETS = [
    '/',
    '/index.html',
    '/manifest.webmanifest',
    '/favicon.svg',
    '/icon-192.png',
    '/icon-512.png',
    '/icon-maskable-192.png',
    '/icon-maskable-512.png',
    '/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        (async () => {
            const cache = await caches.open(SHELL);
            // Individually, so one missing optional asset cannot abort the
            // whole install and leave the app without a shell.
            await Promise.all(
                SHELL_ASSETS.map((url) =>
                    cache.add(new Request(url, { cache: 'reload' })).catch(() => { })
                )
            );
            await self.skipWaiting();
        })()
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        (async () => {
            const keys = await caches.keys();
            await Promise.all(keys.filter((key) => key !== SHELL).map((key) => caches.delete(key)));
            await self.clients.claim();
        })()
    );
});

function isShellRequest(request, url) {
    if (request.method !== 'GET') return false;
    if (url.origin !== self.location.origin) return false;
    // Backend data, authentication and AI: never cached, never intercepted.
    if (url.pathname.startsWith('/api/')) return false;
    // Belt and braces: an authenticated request must not be stored.
    if (request.headers.has('authorization')) return false;
    return true;
}

self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);
    if (!isShellRequest(event.request, url)) return;

    // Navigations: network first, cached shell only when the network fails.
    if (event.request.mode === 'navigate') {
        event.respondWith(
            (async () => {
                try {
                    const response = await fetch(event.request);
                    if (response && response.ok) {
                        const copy = response.clone();
                        event.waitUntil(
                            caches.open(SHELL).then((cache) => cache.put('/index.html', copy)).catch(() => { })
                        );
                    }
                    return response;
                } catch {
                    const cached = (await caches.match('/index.html')) || (await caches.match('/'));
                    return cached || Response.error();
                }
            })()
        );
        return;
    }

    // Content-hashed bundles never change under the same URL: serve from cache
    // without a redundant revalidation on every visit.
    const immutable = url.pathname.startsWith('/assets/');

    event.respondWith(
        (async () => {
            const cached = await caches.match(event.request);
            if (cached && immutable) return cached;

            const network = fetch(event.request)
                .then((response) => {
                    if (response && response.ok) {
                        const copy = response.clone();
                        return caches.open(SHELL)
                            .then((cache) => cache.put(event.request, copy))
                            .then(() => response)
                            .catch(() => response);
                    }
                    return response;
                })
                .catch(() => null);

            if (cached) {
                event.waitUntil(network);
                return cached;
            }

            return (await network) || Response.error();
        })()
    );
});
