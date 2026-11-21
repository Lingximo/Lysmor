/* 极简 Service Worker：只为让浏览器把页面当成可安装的 App。
   不做离线缓存（页面带口令、实时性要求高），所有请求直连网络。 */
self.addEventListener('install', (e) => self.skipWaiting());
self.addEventListener('activate', (e) => self.clients.claim());
self.addEventListener('fetch', (e) => { /* 直连，不缓存 */ });
