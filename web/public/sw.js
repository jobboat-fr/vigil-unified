/* VTLVS — service worker.
 *
 * Il existe pour deux raisons, et pour deux seulement : rendre l'application installable
 * sur mobile (Chrome exige un gestionnaire `fetch`), et afficher un écran utile quand le
 * réseau tombe en salle de formation — ce qui arrive.
 *
 * Ce qu'il ne fait PAS, délibérément :
 *   - il ne met jamais en cache /api : les réponses dépendent du rôle et de la session,
 *     et un cache partagé entre deux comptes sur le même appareil est une fuite ;
 *   - il ne sert jamais une navigation depuis le cache avant d'avoir essayé le réseau,
 *     sinon un déploiement ne prend effet qu'au troisième lancement.
 */
const VERSION = "vtlvs-v1";
const SHELL = ["/", "/logo-mark.png", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((k) => Promise.all(k.filter((n) => n !== VERSION).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // Tout ce qui porte une identité reste hors cache.
  if (url.pathname.startsWith("/api") || url.pathname.startsWith("/v1") || url.pathname.startsWith("/auth")) return;

  // Navigations : réseau d'abord, coquille en secours.
  if (request.mode === "navigate") {
    e.respondWith(fetch(request).catch(() => caches.match("/").then((r) => r || Response.error())));
    return;
  }

  // Fichiers versionnés (/assets/*) : cache d'abord, ils ne changent jamais sous le même nom.
  e.respondWith(
    caches.match(request).then((hit) =>
      hit
      || fetch(request).then((res) => {
        if (res.ok && res.type === "basic") {
          const copy = res.clone();
          caches.open(VERSION).then((c) => c.put(request, copy));
        }
        return res;
      }),
    ),
  );
});
