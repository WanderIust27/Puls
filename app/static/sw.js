/* Minimaler Service Worker: App-Shell cachen, API immer frisch. */
/* Der Cache-Name traegt die Version. Beim Aktivieren wird alles
   Ältere geloescht — sonst haelt der Browser nach einem Update
   weiter die alten Dateien vor. */
const CACHE = "puls-{{V}}";
const SHELL = ["/", "/static/style.css", "/static/app.js",
               "/static/charts.js", "/static/icon.svg", "/manifest.json"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api")) return; // API nie cachen
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
