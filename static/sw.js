// Service worker needed for PWA "Add to Home Screen"
self.addEventListener('fetch', (event) => {
  // Pass-through strategy—fetches from network normally
  event.respondWith(fetch(event.request));
});
