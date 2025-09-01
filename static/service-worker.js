const CACHE_NAME = 'portfolio-tracker-v2'; // Version bump to force update
const STATIC_CACHE_NAME = 'portfolio-static-v2';

// Only cache truly static assets
const urlsToCache = [
  '/static/apple-touch-icon.png',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png',
  '/manifest.webmanifest'
];

// Routes that should NEVER be cached (always fetch fresh)
const neverCacheRoutes = [
  '/',
  '/mobile',
  '/api/live-values',
  '/api/chart-data',
  '/health'
];

// Check if a URL should never be cached
function shouldNeverCache(url) {
  return neverCacheRoutes.some(route => url.pathname === route || url.pathname.startsWith(route));
}

// Check if a URL is a static asset
function isStaticAsset(url) {
  return url.pathname.startsWith('/static/') || 
         urlsToCache.includes(url.pathname);
}

self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(STATIC_CACHE_NAME)
      .then(function(cache) {
        return cache.addAll(urlsToCache);
      })
  );
  // Force immediate activation
  self.skipWaiting();
});

self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then(function(cacheNames) {
      return Promise.all(
        cacheNames.map(function(cacheName) {
          // Delete old caches
          if (cacheName !== STATIC_CACHE_NAME && cacheName !== CACHE_NAME) {
            console.log('Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
  // Force immediate control of all clients
  return self.clients.claim();
});

self.addEventListener('fetch', function(event) {
  const requestUrl = new URL(event.request.url);
  
  // Never cache financial data routes - always fetch fresh
  if (shouldNeverCache(requestUrl)) {
    event.respondWith(
      fetch(event.request).then(function(response) {
        console.log('Fresh fetch for:', requestUrl.pathname);
        return response;
      })
    );
    return;
  }
  
  // Cache static assets only
  if (isStaticAsset(requestUrl)) {
    event.respondWith(
      caches.match(event.request)
        .then(function(response) {
          if (response) {
            return response;
          }
          return fetch(event.request).then(function(response) {
            if (response.status === 200) {
              const responseClone = response.clone();
              caches.open(STATIC_CACHE_NAME).then(function(cache) {
                cache.put(event.request, responseClone);
              });
            }
            return response;
          });
        })
    );
    return;
  }
  
  // For everything else, just fetch (no caching)
  event.respondWith(fetch(event.request));
});