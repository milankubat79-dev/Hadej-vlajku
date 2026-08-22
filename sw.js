// Service Worker — Hádej Vlajku! v5
const CACHE = 'hadej-vlajku-v5';
const OFFLINE_URLS = [
  '/Hadej-vlajku/',
  '/Hadej-vlajku/index.html',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(OFFLINE_URLS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  if(e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if(url.origin !== location.origin) return;

  const isHTML = url.pathname.endsWith('/') || url.pathname.endsWith('.html');

  if(isHTML) {
    // Network-first pro HTML: vždy stáhne nejnovější verzi, cache jen jako záloha offline
    e.respondWith(
      fetch(e.request).then(resp => {
        if(resp && resp.status === 200) {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return resp;
      }).catch(() => caches.match(e.request))
    );
  } else {
    // Cache-first pro ostatní assety (loga, obrázky, ikony…)
    e.respondWith(
      caches.match(e.request).then(cached => {
        if(cached) return cached;
        return fetch(e.request).then(resp => {
          return resp;
        }).catch(() => new Response('Offline', {status: 503}));
      })
    );
  }
});
