/**
 * service-worker.js — PWA shell caching for offline UI viewing.
 *
 * Caches static assets (CSS/JS/HTML shell). Live video and API calls
 * still require network when online.
 */

const CACHE_NAME = "surveillance-shell-v1";
const SHELL_URLS = [
  "/",
  "/static/css/styles.css",
  "/static/js/main.js",
  "/static/js/socket.js",
  "/static/js/timeline.js",
  "/manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Only cache same-origin static shell; never cache MJPEG or API
  if (
    url.origin === self.location.origin &&
    (url.pathname.startsWith("/static/css") ||
      url.pathname.startsWith("/static/js") ||
      url.pathname === "/" ||
      url.pathname === "/manifest.json")
  ) {
    event.respondWith(
      caches.match(event.request).then(
        (cached) =>
          cached ||
          fetch(event.request).then((response) => {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
            return response;
          })
      )
    );
  }
});
