/* Nirvaah service worker.
   Goal: the app opens instantly and survives a dead zone. It is deliberately
   NOT an API cache — money data must always come from the server, so anything
   under /api/ goes straight to the network. */

const SHELL = 'nirvaah-shell-v1';
const SHELL_ASSETS = ['/', '/index.html', '/manifest.webmanifest', '/favicon.svg', '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(SHELL).then(cache => cache.addAll(SHELL_ASSETS)).then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys()
            .then(keys => Promise.all(keys.filter(k => k !== SHELL).map(k => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', event => {
    const { request } = event;
    if (request.method !== 'GET') return;

    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;
    if (url.pathname.startsWith('/api/')) return; // never cached, never stale

    // Navigations: network first, shell from cache when offline.
    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request)
                .then(res => {
                    const copy = res.clone();
                    caches.open(SHELL).then(cache => cache.put('/index.html', copy));
                    return res;
                })
                .catch(() => caches.match('/index.html').then(hit => hit || caches.match('/')))
        );
        return;
    }

    // Assets: cache first, refresh in the background.
    event.respondWith(
        caches.match(request).then(hit => {
            const network = fetch(request)
                .then(res => {
                    if (res && res.ok) {
                        const copy = res.clone();
                        caches.open(SHELL).then(cache => cache.put(request, copy));
                    }
                    return res;
                })
                .catch(() => hit);
            return hit || network;
        })
    );
});
