const cacheName = "irus-v1";
const files = [
  "/dashboard",
  "/static/style.css",
  "/static/logo.png",
  // add more assets here
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(cacheName).then((cache) => cache.addAll(files))
  );
});

self.addEventListener("fetch", (e) => {
  e.respondWith(
    caches.match(e.request).then((res) => res || fetch(e.request))
  );
});