// Web Push handlers (ADR-0010), imported into the generated service worker via
// workbox `importScripts` — the generateSW strategy stays (shell precache only;
// ADR-0005 keeps offline data in the page's IndexedDB queue, never the SW).
//
// The payload is the JSON `app.services.push.rest_timer_payload` builds:
// {title, body, url, tag}. The fixed tag makes a newer rest notification
// replace a stale one instead of stacking.

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    // Malformed payload — fall through to the generic cue below.
  }
  const title = data.title || 'Rest over';
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || '',
      tag: data.tag || 'rest-timer',
      icon: '/pwa-192x192.png',
      badge: '/pwa-192x192.png',
      data: { url: data.url || '/' },
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    (async () => {
      const wins = await clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const win of wins) {
        if ('focus' in win) {
          await win.focus();
          if ('navigate' in win) await win.navigate(url);
          return;
        }
      }
      await clients.openWindow(url);
    })(),
  );
});
