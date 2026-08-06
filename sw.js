/* FinGuard service worker
 *
 * __BUILD_VERSION__ is replaced by the GitHub Actions deploy job with the
 * short commit SHA. That means every push produces a new cache name, which
 * is what makes updates land without anyone bumping a number by hand.
 */
const VERSION = '__BUILD_VERSION__';
const SHELL_CACHE = `finguard-shell-${VERSION}`;
const FONT_CACHE = 'finguard-fonts';           // survives version bumps
const SHELL_KEEP = new Set([SHELL_CACHE, FONT_CACHE]);

const SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './version.json',
  './icons/icon-180.png',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png',
  './icons/favicon.png',
];

const FONT_HOSTS = ['fonts.googleapis.com', 'fonts.gstatic.com'];

/* ---------- install ---------- */
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then(cache =>
      // addAll is all-or-nothing; add individually so one 404 can't
      // block the whole install and leave the app stuck on the old build.
      Promise.all(SHELL.map(url =>
        cache.add(new Request(url, { cache: 'reload' })).catch(() => null)
      ))
    )
    // No skipWaiting() here on purpose. The page decides when to swap,
    // so an update can't reload the screen while someone is typing.
  );
});

/* ---------- activate ---------- */
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(
      names.filter(n => n.startsWith('finguard-') && !SHELL_KEEP.has(n))
           .map(n => caches.delete(n))
    );
    if (self.registration.navigationPreload) {
      await self.registration.navigationPreload.enable();
    }
    await self.clients.claim();
  })());
});

/* ---------- page asks us to take over ---------- */
self.addEventListener('message', event => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
  if (event.data === 'GET_VERSION' && event.source) {
    event.source.postMessage({ type: 'VERSION', version: VERSION });
  }
});

/* ---------- fetch ---------- */
self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Fonts: cache-first, kept across deploys so an update doesn't cause
  // a flash of fallback type.
  if (FONT_HOSTS.includes(url.hostname)) {
    event.respondWith(cacheFirst(req, FONT_CACHE));
    return;
  }

  if (url.origin !== self.location.origin) return;

  // version.json must always be truthful — never serve it from cache.
  if (url.pathname.endsWith('/version.json')) {
    event.respondWith(
      fetch(req, { cache: 'no-store' }).catch(() => caches.match(req))
    );
    return;
  }

  // Navigations: network-first so a fresh index.html wins whenever online.
  if (req.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        const preload = await event.preloadResponse;
        const fresh = preload || await fetch(req);
        const cache = await caches.open(SHELL_CACHE);
        cache.put('./index.html', fresh.clone());
        return fresh;
      } catch {
        return (await caches.match('./index.html')) ||
               (await caches.match('./')) ||
               new Response('離線中，且沒有快取版本可用。', {
                 status: 503,
                 headers: { 'Content-Type': 'text/plain; charset=utf-8' },
               });
      }
    })());
    return;
  }

  // Everything else: serve cache immediately, refresh in the background.
  event.respondWith(staleWhileRevalidate(req, SHELL_CACHE));
});

async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok || res.type === 'opaque') cache.put(req, res.clone());
  return res;
}

async function staleWhileRevalidate(req, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req);
  const network = fetch(req).then(res => {
    if (res.ok) cache.put(req, res.clone());
    return res;
  }).catch(() => null);
  return hit || (await network) || new Response('', { status: 504 });
}
