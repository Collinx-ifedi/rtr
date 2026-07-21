/* ================================================================
   RTR ADMIN — admin.js
   Rocky Trendy Realities · Vanilla JS Admin Runtime (ES2022+)
   Single deployable file · no bundler · no framework
   Pages: admin-dashboard.html · admin-products.html · admin-content.html
   Auto page detection via document.body.dataset.page
   ================================================================ */
(() => {
  'use strict';

  /* ==============================================================
     CONFIGURATION
     ============================================================== */
  const CONFIG = Object.freeze({
    API_BASE: '',                       // same-origin FastAPI
    REQUEST_TIMEOUT: 20000,
    MAX_RETRIES: 2,
    RETRY_DELAY: 600,
    TOKEN_KEY: 'rtr_admin_token',
    ADMIN_KEY: 'rtr_admin_profile',
    LOGIN_URL: '/admin-login.html',
    CURRENCY: 'NGN',
    DEBUG: /[?&]debug=1/.test(location.search),
    FEATURES: { charts: true, export: true, keyboardShortcuts: true },
  });

  /* ==============================================================
     CONSTANTS
     ============================================================== */
  const CATEGORY_MAP = Object.freeze({
    sofa: 'Sofas & Seating', table: 'Tables & Desks', dining: 'Dining',
    bedroom: 'Bedroom', office: 'Office', finish: 'Home Finishes', decor: 'Decor & Accents',
  });

  const ORDER_STATUS = Object.freeze({
    pending: 'pending', paid: 'paid', processing: 'processing', shipped: 'shipped',
    delivered: 'delivered', cancelled: 'cancelled', refunded: 'refunded', failed: 'failed',
  });

  const PAGE_SIZE_DEFAULT = 12;

  /* ==============================================================
     STRUCTURED LOGGING / DEBUG
     ============================================================== */
  const Log = {
    _t0: performance.now(),
    info: (...a) => CONFIG.DEBUG && console.log('%c[RTR]', 'color:#C4956A', ...a),
    warn: (...a) => console.warn('[RTR]', ...a),
    error: (...a) => console.error('[RTR]', ...a),
    time: (label) => CONFIG.DEBUG && console.time(`[RTR] ${label}`),
    timeEnd: (label) => CONFIG.DEBUG && console.timeEnd(`[RTR] ${label}`),
  };

  /* ==============================================================
     DOM HELPERS
     ============================================================== */
  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const on = (el, evt, handler, opts) => el && el.addEventListener(evt, handler, opts);
  const off = (el, evt, handler, opts) => el && el.removeEventListener(evt, handler, opts);

  const el = (tag, props = {}, children = []) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === 'class') node.className = v;
      else if (k === 'dataset') Object.assign(node.dataset, v);
      else if (k === 'html') node.innerHTML = v;             // caller must pre-escape
      else if (k === 'text') node.textContent = v;
      else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined) node.setAttribute(k, v);
    }
    (Array.isArray(children) ? children : [children]).forEach((c) => {
      if (c == null) return;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return node;
  };

  const clear = (node) => { while (node && node.firstChild) node.removeChild(node.firstChild); };
  const refreshIcons = () => { if (window.lucide) window.lucide.createIcons(); };

  /* ==============================================================
     UTILITY FUNCTIONS — DEBOUNCE / THROTTLE
     ============================================================== */
  const debounce = (fn, wait = 250) => {
    let t; const d = (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); };
    d.cancel = () => clearTimeout(t); return d;
  };
  const throttle = (fn, limit = 200) => {
    let inThrottle, lastArgs;
    return (...args) => {
      lastArgs = args;
      if (!inThrottle) {
        fn(...lastArgs); inThrottle = true;
        setTimeout(() => { inThrottle = false; }, limit);
      }
    };
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  /* ==============================================================
     SECURITY — XSS PREVENTION / SANITIZATION / ESCAPING
     ============================================================== */
  const escapeHTML = (str) => String(str ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
  const sanitizeInput = (str, max = 5000) => String(str ?? '').replace(/[\u0000-\u001F\u007F]/g, '').slice(0, max).trim();
  const safeURL = (url) => {
    try { const u = new URL(url, location.origin); return ['http:', 'https:'].includes(u.protocol) ? u.href : ''; }
    catch { return ''; }
  };

  /* ==============================================================
     FORMATTERS
     ============================================================== */
  const Fmt = {
    money: (n) => `\u20A6${Number(n || 0).toLocaleString('en-NG', { maximumFractionDigits: 0 })}`,
    moneyShort: (n) => {
      n = Number(n || 0);
      if (n >= 1e9) return `\u20A6${(n / 1e9).toFixed(1)}B`;
      if (n >= 1e6) return `\u20A6${(n / 1e6).toFixed(1)}M`;
      if (n >= 1e3) return `\u20A6${(n / 1e3).toFixed(0)}K`;
      return `\u20A6${n.toFixed(0)}`;
    },
    number: (n) => Number(n || 0).toLocaleString('en-NG'),
    date: (d) => { const x = new Date(d); return isNaN(x) ? '—' : x.toLocaleDateString('en-NG', { year: 'numeric', month: 'short', day: 'numeric' }); },
    dateTime: (d) => { const x = new Date(d); return isNaN(x) ? '—' : x.toLocaleString('en-NG', { dateStyle: 'medium', timeStyle: 'short' }); },
    relative: (d) => {
      const x = new Date(d); if (isNaN(x)) return '—';
      const diff = (Date.now() - x.getTime()) / 1000;
      if (diff < 60) return 'just now';
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
      if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
      if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
      return Fmt.date(d);
    },
    initials: (name = '') => name.trim().split(/\s+/).map((p) => p[0] || '').slice(0, 2).join('').toUpperCase() || 'NA',
    titleCase: (s = '') => String(s).replace(/[_-]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
    percent: (n) => `${Number(n || 0).toFixed(1)}%`,
  };

  /* ==============================================================
     VALIDATORS
     ============================================================== */
  const Validate = {
    required: (v) => String(v ?? '').trim().length > 0,
    email: (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(v || '').trim()),
    number: (v) => v !== '' && !isNaN(Number(v)),
    positive: (v) => Validate.number(v) && Number(v) > 0,
    nonNegative: (v) => Validate.number(v) && Number(v) >= 0,
    minLen: (v, n) => String(v ?? '').trim().length >= n,
    url: (v) => !v || /^https?:\/\//i.test(v),
  };

  /* ==============================================================
     EVENT BUS
     ============================================================== */
  const EventBus = (() => {
    const map = new Map();
    return {
      on(evt, cb) { (map.get(evt) || map.set(evt, new Set()).get(evt)).add(cb); return () => EventBus.off(evt, cb); },
      off(evt, cb) { map.get(evt)?.delete(cb); },
      emit(evt, payload) { map.get(evt)?.forEach((cb) => { try { cb(payload); } catch (e) { Log.error('bus', evt, e); } }); },
    };
  })();

  /* ==============================================================
     STORAGE MANAGER
     ============================================================== */
  const Storage = {
    _safe(fn, fallback) { try { return fn(); } catch { return fallback; } },
    get(key, fallback = null) { return this._safe(() => { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); }, fallback); },
    set(key, val) { this._safe(() => localStorage.setItem(key, JSON.stringify(val))); },
    remove(key) { this._safe(() => localStorage.removeItem(key)); },
    session: {
      get(key, fb = null) { try { const v = sessionStorage.getItem(key); return v === null ? fb : JSON.parse(v); } catch { return fb; } },
      set(key, val) { try { sessionStorage.setItem(key, JSON.stringify(val)); } catch {} },
    },
    prefs: {
      get(k, fb) { const p = Storage.get('rtr_prefs', {}); return k in p ? p[k] : fb; },
      set(k, v) { const p = Storage.get('rtr_prefs', {}); p[k] = v; Storage.set('rtr_prefs', p); },
    },
  };

  /* ==============================================================
     STATE MANAGER (lightweight reactive store)
     ============================================================== */
  const Store = (() => {
    const state = {
      auth: { token: null, admin: null },
      products: [], orders: [], customers: [], analytics: null,
      heroes: [], banners: [],
      ui: { sidebarOpen: false, loading: false },
      cache: {},
    };
    const subs = new Map();
    const notify = (key) => subs.get(key)?.forEach((cb) => { try { cb(state[key]); } catch (e) { Log.error(e); } });
    return {
      get: (key) => state[key],
      set(key, value) { state[key] = value; notify(key); EventBus.emit(`state:${key}`, value); },
      patch(key, partial) { state[key] = { ...state[key], ...partial }; notify(key); },
      subscribe(key, cb) { (subs.get(key) || subs.set(key, new Set()).get(key)).add(cb); return () => subs.get(key)?.delete(cb); },
      // simple TTL cache used to prevent duplicate API calls
      cacheGet(key, ttl = 30000) { const c = state.cache[key]; return c && (Date.now() - c.t < ttl) ? c.v : undefined; },
      cacheSet(key, v) { state.cache[key] = { v, t: Date.now() }; },
      invalidate(key) { if (key) delete state.cache[key]; else state.cache = {}; },
    };
  })();

  /* ==============================================================
     API CLIENT
     ============================================================== */
  class APIError extends Error {
    constructor(message, status, data) { super(message); this.name = 'APIError'; this.status = status; this.data = data; }
  }

  const APIClient = (() => {
    const authHeaders = () => {
      const token = Auth.getToken();
      const h = {};
      if (token) h['Authorization'] = `Bearer ${token}`;
      return h;
    };

    async function request(method, url, { body, json, headers = {}, timeout = CONFIG.REQUEST_TIMEOUT, retries = CONFIG.MAX_RETRIES, signal } = {}) {
      const full = CONFIG.API_BASE + url;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeout);
      if (signal) signal.addEventListener('abort', () => controller.abort());

      const opts = { method, headers: { ...authHeaders(), ...headers }, signal: controller.signal };
      if (json !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(json); }
      else if (body !== undefined) { opts.body = body; } // FormData — let browser set boundary

      let attempt = 0, lastErr;
      while (attempt <= retries) {
        try {
          Log.info(`${method} ${url}`, attempt ? `(retry ${attempt})` : '');
          const res = await fetch(full, opts);
          clearTimeout(timer);

          if (res.status === 401) { Auth.handleUnauthorized(); throw new APIError('Unauthorized', 401); }
          const ct = res.headers.get('content-type') || '';
          const payload = ct.includes('application/json') ? await res.json().catch(() => null) : await res.text();

          if (!res.ok) {
            const detail = (payload && payload.detail) || (typeof payload === 'string' ? payload : `Request failed (${res.status})`);
            throw new APIError(Array.isArray(detail) ? detail.map((d) => d.msg).join(', ') : detail, res.status, payload);
          }
          return payload;
        } catch (err) {
          lastErr = err;
          clearTimeout(timer);
          if (err.name === 'AbortError') throw new APIError('Request timed out', 0);
          if (err instanceof APIError && err.status && err.status < 500) throw err; // don't retry client errors
          if (attempt === retries) break;
          await sleep(CONFIG.RETRY_DELAY * (attempt + 1));
          attempt++;
        }
      }
      throw lastErr instanceof APIError ? lastErr : new APIError(lastErr?.message || 'Network error', 0);
    }

    return {
      get: (url, opts) => request('GET', url, opts),
      post: (url, json, opts) => request('POST', url, { json, ...opts }),
      put: (url, json, opts) => request('PUT', url, { json, ...opts }),
      patch: (url, json, opts) => request('PATCH', url, { json, ...opts }),
      delete: (url, opts) => request('DELETE', url, opts),
      upload: (url, formData, method = 'POST', opts) => request(method, url, { body: formData, ...opts }),
    };
  })();

  /* Domain-specific API surface mapped to the FastAPI backend */
  const API = {
    login: (username, password) => APIClient.post('/api/admin/login', { username, password }),
    stats: () => APIClient.get('/api/admin/stats'),
    users: (params = {}) => APIClient.get(`/api/admin/users${qs(params)}`),
    banUser: (id) => APIClient.post(`/api/admin/users/${id}/ban`),
    unbanUser: (id) => APIClient.post(`/api/admin/users/${id}/unban`),
    orders: (params = {}) => APIClient.get(`/api/admin/orders${qs(params)}`),
    orderAction: (id, action, manual_content) => APIClient.post(`/api/admin/orders/${id}/action`, { action, manual_content }),
    products: () => APIClient.get('/api/admin/products'),
    createProduct: (fd) => APIClient.upload('/api/admin/products', fd, 'POST',{retries:0}),
    updateProduct: (id, fd) => APIClient.upload(`/api/admin/products/${id}`, fd, 'PUT',{retries:0}),
    deleteProduct: (id) => APIClient.delete(`/api/admin/products/${id}`, { retries: 0 }),
    banners: (active = true) => APIClient.get(`/api/banners?active=${active}`),
    createBanner: (fd) => APIClient.upload('/api/admin/banners', fd, 'POST', { retries: 0 }),
    deleteBanner: (id) => APIClient.delete(`/api/admin/banners/${id}`, { retries: 0 }),
    publicProducts: (params = {}) => APIClient.get(`/api/products${qs(params)}`),
  };
  const qs = (params) => {
    const q = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');
    return q ? `?${q}` : '';
  };

  /* ==============================================================
     AUTHENTICATION MANAGER
     ============================================================== */
  const Auth = {
    getToken() { return Store.get('auth').token || Storage.get(CONFIG.TOKEN_KEY); },
    getAdmin() { return Store.get('auth').admin || Storage.get(CONFIG.ADMIN_KEY); },
    isAuthed() { return !!this.getToken(); },
    async login(username, password) {
      const res = await API.login(username, password);
      Storage.set(CONFIG.TOKEN_KEY, res.access_token);
      Storage.set(CONFIG.ADMIN_KEY, res.admin || null);
      Store.set('auth', { token: res.access_token, admin: res.admin || null });
      EventBus.emit('auth:login', res.admin);
      return res;
    },
    logout() {
      Storage.remove(CONFIG.TOKEN_KEY); Storage.remove(CONFIG.ADMIN_KEY);
      Store.set('auth', { token: null, admin: null });
      EventBus.emit('auth:logout');
      location.href = CONFIG.LOGIN_URL;
    },
    handleUnauthorized() {
      Notify.error('Your session has expired. Please sign in again.');
      Storage.remove(CONFIG.TOKEN_KEY);
      Storage.remove(CONFIG.ADMIN_KEY);
      Store.set('auth', { token: null, admin: null });
      EventBus.emit('auth:expired');
      window.location.href = CONFIG.LOGIN_URL;
    },
    hydrate() {
      const token = Storage.get(CONFIG.TOKEN_KEY);
      const admin = Storage.get(CONFIG.ADMIN_KEY);
      Store.set('auth', { token, admin });
      // Reflect admin identity in the sidebar/topbar if present
      if (admin) {
        $$('.js-admin-name').forEach((n) => (n.textContent = admin.username || 'Admin'));
        $$('.js-admin-role').forEach((n) => (n.textContent = Fmt.titleCase(admin.role || 'admin')));
        $$('.js-admin-initials').forEach((n) => (n.textContent = Fmt.initials(admin.username || 'AD')));
      }
    },
  };

  /* ==============================================================
     NOTIFICATION MANAGER (toasts)
     ============================================================== */
  const Notify = (() => {
    let stack;
    const icons = {
      success: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
      error: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
      warning: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      info: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    };
    const ensure = () => { if (!stack) { stack = el('div', { class: 'toast-stack', 'aria-live': 'polite', role: 'status' }); document.body.appendChild(stack); } return stack; };
    const show = (msg, type = 'success', ms = 3200) => {
      const t = el('div', { class: `toast ${type}` });
      t.innerHTML = `<span class="ti">${icons[type] || icons.info}</span><span>${escapeHTML(msg)}</span>`;
      ensure().appendChild(t);
      requestAnimationFrame(() => t.classList.add('show'));
      const close = () => { t.classList.remove('show'); setTimeout(() => t.remove(), 300); };
      const timer = setTimeout(close, ms);
      on(t, 'click', () => { clearTimeout(timer); close(); });
      return close;
    };
    return {
      show, success: (m, ms) => show(m, 'success', ms), error: (m, ms) => show(m, 'error', ms || 4500),
      warning: (m, ms) => show(m, 'warning', ms), info: (m, ms) => show(m, 'info', ms),
    };
  })();

  /* ==============================================================
     LOADING OVERLAY
     ============================================================== */
  const Loader = {
    _node: null,
    _ensure() { if (!this._node) { this._node = el('div', { class: 'loading-overlay', html: '<div class="spinner"></div><div class="loading-text">Loading…</div>' }); document.body.appendChild(this._node); } return this._node; },
    show(text = 'Loading…') { const n = this._ensure(); $('.loading-text', n).textContent = text; n.classList.add('on'); },
    hide() { this._node && this._node.classList.remove('on'); },
  };

  /* ==============================================================
     MODAL MANAGER (with focus trap + escape handling)
     ============================================================== */
  const Modal = (() => {
    let active = null, lastFocused = null;
    const focusable = 'a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex="-1"])';
    const trap = (e) => {
      if (e.key !== 'Tab' || !active) return;
      const nodes = $$(focusable, active).filter((n) => n.offsetParent !== null);
      if (!nodes.length) return;
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    return {
      open(id) {
        const bg = typeof id === 'string' ? document.getElementById(id) : id;
        if (!bg) return;
        lastFocused = document.activeElement;
        bg.classList.add('on'); bg.setAttribute('aria-hidden', 'false');
        active = bg; document.body.style.overflow = 'hidden';
        setTimeout(() => { const f = $(focusable, bg); f && f.focus(); }, 40);
        document.addEventListener('keydown', trap);
        EventBus.emit('modal:open', bg.id);
      },
      close(id) {
        const bg = id ? (typeof id === 'string' ? document.getElementById(id) : id) : active;
        if (!bg) return;
        bg.classList.remove('on'); bg.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
        document.removeEventListener('keydown', trap);
        if (active === bg) active = null;
        lastFocused && lastFocused.focus?.();
        EventBus.emit('modal:close', bg.id);
      },
      closeAll() { $$('.modal-bg.on').forEach((m) => this.close(m)); },
      init() {
        // backdrop click + [data-close] + escape
        on(document, 'click', (e) => {
          if (e.target.classList?.contains('modal-bg')) this.close(e.target);
          const closer = e.target.closest('[data-modal-close]');
          if (closer) this.close(closer.closest('.modal-bg'));
          const opener = e.target.closest('[data-modal-open]');
          if (opener) this.open(opener.dataset.modalOpen);
        });
        on(document, 'keydown', (e) => { if (e.key === 'Escape' && active) this.close(); });
      },
    };
  })();

  /* ==============================================================
     DRAWER MANAGER
     ============================================================== */
  const Drawer = {
    open(id) { const d = document.getElementById(id); if (!d) return; d.classList.add('on'); const bg = document.getElementById(`${id}-bg`); bg && bg.classList.add('on'); document.body.style.overflow = 'hidden'; },
    close(id) { const d = document.getElementById(id); if (!d) return; d.classList.remove('on'); const bg = document.getElementById(`${id}-bg`); bg && bg.classList.remove('on'); document.body.style.overflow = ''; },
    init() {
      on(document, 'click', (e) => {
        const o = e.target.closest('[data-drawer-open]'); if (o) this.open(o.dataset.drawerOpen);
        const c = e.target.closest('[data-drawer-close]'); if (c) this.close(c.dataset.drawerClose || c.closest('.drawer')?.id);
        if (e.target.classList?.contains('drawer-bg')) this.close(e.target.id.replace('-bg', ''));
      });
    },
  };

  /* ==============================================================
     DROPDOWN MANAGER
     ============================================================== */
  const Dropdown = {
    init() {
      on(document, 'click', (e) => {
        const trigger = e.target.closest('[data-dropdown]');
        if (trigger) {
          const menu = document.getElementById(trigger.dataset.dropdown);
          const isOpen = menu?.classList.contains('open');
          $$('.dropdown-menu.open').forEach((m) => m.classList.remove('open'));
          if (menu && !isOpen) menu.classList.add('open');
          e.stopPropagation();
          return;
        }
        if (!e.target.closest('.dropdown-menu')) $$('.dropdown-menu.open').forEach((m) => m.classList.remove('open'));
      });
      on(document, 'keydown', (e) => { if (e.key === 'Escape') $$('.dropdown-menu.open').forEach((m) => m.classList.remove('open')); });
    },
  };

  /* ==============================================================
     TOOLTIP MANAGER (CSS driven via [data-tip]; JS ensures a11y)
     ============================================================== */
  const Tooltip = { init() { $$('[data-tip]').forEach((n) => { if (!n.getAttribute('aria-label')) n.setAttribute('aria-label', n.dataset.tip); }); } };

  /* ==============================================================
     RESPONSIVE NAVIGATION MODULE
     ============================================================== */
  const Nav = {
    init() {
      const sidebar = $('#sidebar');
      const overlay = $('#sb-overlay') || (() => { const o = el('div', { class: 'sb-overlay', id: 'sb-overlay' }); document.body.prepend(o); return o; })();
      const openMob = () => { sidebar?.classList.add('open'); overlay.classList.add('on'); };
      const closeMob = () => { sidebar?.classList.remove('open'); overlay.classList.remove('on'); };
      on($('.mob-toggle'), 'click', openMob);
      on(overlay, 'click', closeMob);
      $$('#sidebar .sb-link').forEach((l) => on(l, 'click', () => window.innerWidth <= 768 && closeMob()));
      // active-link highlight based on current file
      const file = location.pathname.split('/').pop() || 'admin-dashboard.html';
      $$('#sidebar .sb-link[data-href]').forEach((l) => { if (l.dataset.href === file) l.classList.add('active'); });
      EventBus.on('nav:closeMobile', closeMob);
    },
  };

  /* ==============================================================
     THEME MODULE (persists density / reduced-motion prefs)
     ============================================================== */
  const Theme = {
    init() {
      const density = Storage.prefs.get('density', 'comfortable');
      document.body.dataset.density = density;
    },
  };

  /* ==============================================================
     KEYBOARD SHORTCUT MODULE
     ============================================================== */
  const Shortcuts = {
    init() {
      if (!CONFIG.FEATURES.keyboardShortcuts) return;
      on(document, 'keydown', (e) => {
        const tag = document.activeElement?.tagName;
        const typing = tag === 'INPUT' || tag === 'TEXTAREA' || document.activeElement?.isContentEditable;
        if ((e.key === '/' || (e.key === 'k' && (e.metaKey || e.ctrlKey))) && !typing) {
          e.preventDefault(); const s = $('.tb-search input') || $('.search-input'); s && s.focus();
        }
        if (e.key === 'Escape' && typing) document.activeElement.blur();
      });
    },
  };

  /* ==============================================================
     EXPORT MODULE (client-side CSV)
     ============================================================== */
  const Exporter = {
    toCSV(rows, filename = 'export.csv') {
      if (!rows || !rows.length) { Notify.warning('Nothing to export.'); return; }
      const headers = Object.keys(rows[0]);
      const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
      const csv = [headers.join(','), ...rows.map((r) => headers.map((h) => escape(r[h])).join(','))].join('\r\n');
      const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = el('a', { href: url, download: filename });
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      Notify.success('Export ready.');
    },
  };

  /* ==============================================================
     CHARTS MODULE (dependency-free bar + donut renderers)
     ============================================================== */
  const Charts = {
    bars(container, data, { format = Fmt.moneyShort } = {}) {
      if (!container) return;
      clear(container);
      const row = el('div', { class: 'chart-bars' });
      const max = Math.max(...data.map((d) => d.value), 1);
      data.forEach((d, i) => {
        const wrap = el('div', { class: 'chart-bar-wrap' });
        const bar = el('div', { class: 'chart-bar', style: 'height:0%', 'aria-label': `${d.label}: ${format(d.value)}` });
        bar.appendChild(el('span', { class: 'chart-bar-tip', text: format(d.value) }));
        wrap.appendChild(bar);
        wrap.appendChild(el('span', { class: 'chart-label', text: d.label }));
        row.appendChild(wrap);
        requestAnimationFrame(() => setTimeout(() => { bar.style.height = `${(d.value / max) * 100}%`; }, i * 45));
      });
      container.appendChild(row);
    },
    donut(container, segments) {
      if (!container) return;
      const palette = ['var(--caramel)', 'var(--brown)', 'var(--info)', 'var(--accent)', 'rgba(196,149,106,.2)'];
      const total = segments.reduce((s, x) => s + x.value, 0) || 1;
      let acc = 0; const stops = [];
      segments.forEach((s, i) => { const start = (acc / total) * 100; acc += s.value; const end = (acc / total) * 100; stops.push(`${palette[i % palette.length]} ${start}% ${end}%`); });
      const donut = $('.donut', container) || container;
      donut.style.background = `conic-gradient(${stops.join(',')})`;
      const legend = $('.donut-legend', container);
      if (legend) {
        clear(legend);
        segments.forEach((s, i) => {
          const item = el('div', { class: 'dl-item' });
          item.innerHTML = `<span class="dl-dot" style="background:${palette[i % palette.length]}"></span><span class="dl-name">${escapeHTML(s.label)}</span><span class="dl-pct">${Math.round((s.value / total) * 100)}%</span>`;
          legend.appendChild(item);
        });
      }
    },
  };

  /* ==============================================================
     PAGINATION MODULE
     ============================================================== */
  class Paginator {
    constructor({ pageSize = PAGE_SIZE_DEFAULT } = {}) { this.pageSize = pageSize; this.page = 1; this.total = 0; }
    setTotal(n) { this.total = n; this.pages = Math.max(1, Math.ceil(n / this.pageSize)); if (this.page > this.pages) this.page = this.pages; return this; }
    slice(arr) { const start = (this.page - 1) * this.pageSize; return arr.slice(start, start + this.pageSize); }
    render(container, onChange) {
      if (!container) return;
      clear(container);
      if (this.total <= this.pageSize) return;
      const info = el('div', { class: 'pagination-info', text: `Page ${this.page} of ${this.pages} · ${this.total} items` });
      const controls = el('div', { class: 'pagination-controls' });
      const mkBtn = (label, page, opts = {}) => {
        const b = el('button', { class: `page-btn ${opts.active ? 'active' : ''}`, text: label });
        if (opts.disabled) b.disabled = true;
        on(b, 'click', () => { this.page = page; onChange(); });
        return b;
      };
      controls.appendChild(mkBtn('‹', this.page - 1, { disabled: this.page === 1 }));
      const range = this._range();
      range.forEach((p) => controls.appendChild(p === '…' ? el('span', { class: 'page-btn', text: '…' }) : mkBtn(String(p), p, { active: p === this.page })));
      controls.appendChild(mkBtn('›', this.page + 1, { disabled: this.page === this.pages }));
      container.appendChild(info); container.appendChild(controls);
    }
    _range() {
      const { page, pages } = this; const out = [];
      const push = (n) => out.push(n);
      if (pages <= 7) { for (let i = 1; i <= pages; i++) push(i); return out; }
      push(1);
      if (page > 3) push('…');
      for (let i = Math.max(2, page - 1); i <= Math.min(pages - 1, page + 1); i++) push(i);
      if (page < pages - 2) push('…');
      push(pages);
      return out;
    }
  }

  /* ==============================================================
     DASHBOARD MODULE
     ============================================================== */
  const DashboardModule = {
    async init() {
      Log.time('dashboard');
      this.bindQuickActions();
      await Promise.allSettled([this.loadStats(), this.loadRecentOrders(), this.loadCharts()]);
      Log.timeEnd('dashboard');
    },
    async loadStats() {
      try {
        const s = await API.stats();
        this.setStat('kpi-revenue', Fmt.moneyShort(s.total_sales));
        this.setStat('kpi-orders', Fmt.number(s.total_orders));
        this.setStat('kpi-customers', Fmt.number(s.total_users));
        this.setStat('kpi-pending', Fmt.number(s.open_orders));
        const products = await this.safeProducts();
        this.setStat('kpi-products', Fmt.number(products.length));
        const aov = s.total_orders ? s.total_sales / s.total_orders : 0;
        this.setStat('kpi-aov', Fmt.moneyShort(aov));
      } catch (e) { Log.warn('stats failed', e.message); this.markStatsUnavailable(); }
    },
    setStat(id, val) { const n = document.getElementById(id); if (n) { n.textContent = val; n.style.animation = 'countUp .4s ease'; } },
    markStatsUnavailable() { $$('.js-kpi-value').forEach((n) => { if (!n.textContent.trim() || n.textContent === '—') n.textContent = '—'; }); },
    async safeProducts() { try { const c = Store.cacheGet('products'); if (c) return c; const p = await API.products(); Store.cacheSet('products', p); Store.set('products', p); return p; } catch { return Store.get('products') || []; } },
    async loadRecentOrders() {
      const body = $('#recent-orders-body'); if (!body) return;
      try {
        const orders = await API.orders({ limit: 6 });
        Store.set('orders', orders);
        if (!orders.length) { body.innerHTML = `<tr><td colspan="7">${OrdersModule.emptyRow('No orders yet')}</td></tr>`; return; }
        clear(body);
        orders.forEach((o) => body.appendChild(OrdersModule.compactRow(o)));
      } catch (e) {
        Log.warn('recent orders', e.message);
        body.innerHTML = `<tr><td colspan="7">${OrdersModule.emptyRow('Unable to load orders')}</td></tr>`;
      }
      refreshIcons();
    },
    async loadCharts() {
      if (!CONFIG.FEATURES.charts) return;
      const rev = $('#rev-chart');
      if (rev) {
        // Fetch independently rather than reading Store.get('orders') — that store is
        // only populated once loadRecentOrders()'s own await resolves, and since both
        // run concurrently via Promise.allSettled in init(), reading it here raced and
        // was always empty, so the chart rendered with every bucket at zero.
        let orders = [];
        try { orders = await API.orders({ limit: 100 }); } catch (e) { Log.warn('revenue chart orders', e.message); }

        // Bucket by actual calendar day (today and the 6 days before it) to match the
        // "Last 7 days" label — grouping by weekday name alone would silently merge
        // orders from different weeks into the same bar.
        const dayLabels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        const today = new Date(); today.setHours(0, 0, 0, 0);
        const buckets = Array.from({ length: 7 }, (_, i) => {
          const d = new Date(today); d.setDate(d.getDate() - (6 - i));
          return { label: dayLabels[d.getDay()], date: d, value: 0 };
        });
        orders.forEach((o) => {
          const created = new Date(o.created_at); created.setHours(0, 0, 0, 0);
          const bucket = buckets.find((b) => b.date.getTime() === created.getTime());
          if (bucket) bucket.value += Number(o.total_amount || 0);
        });
        Charts.bars(rev, buckets);
      }
      const donut = $('#category-donut');
      if (donut) {
        const products = await this.safeProducts();
        const byCat = {};
        products.forEach((p) => { const c = p.product_category || 'decor'; byCat[c] = (byCat[c] || 0) + 1; });
        const segs = Object.entries(byCat).map(([k, v]) => ({ label: CATEGORY_MAP[k] || Fmt.titleCase(k), value: v }));
        Charts.donut(donut, segs.length ? segs : [{ label: 'No data', value: 1 }]);
      }
    },
    bindQuickActions() {
      $$('[data-quick]').forEach((btn) => on(btn, 'click', () => {
        const to = btn.dataset.quick;
        const routes = { 'add-product': 'admin-products.html', 'orders': 'admin-dashboard.html', 'banner': 'admin-content.html' };
        if (routes[to]) location.href = routes[to];
      }));
    },
  };

  /* ==============================================================
     ANALYTICS MODULE
     ============================================================== */
  const AnalyticsModule = {
    async init() {
      const [products] = await Promise.all([DashboardModule.safeProducts()]);
      this.renderTopProducts(products);
      this.renderMonthly();
    },
    renderMonthly() {
      const c = $('#monthly-chart'); if (!c) return;
      const orders = Store.get('orders') || [];
      const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      const buckets = months.map((m) => ({ label: m, value: 0 }));
      orders.forEach((o) => { const m = new Date(o.created_at).getMonth(); if (buckets[m]) buckets[m].value += Number(o.total_amount || 0); });
      Charts.bars(c, buckets);
    },
    renderTopProducts(products) {
      const list = $('#top-products-list'); if (!list) return;
      clear(list);
      const top = [...products].sort((a, b) => (b.price || 0) - (a.price || 0)).slice(0, 6);
      if (!top.length) { list.innerHTML = UI.empty('package', 'No products yet', ''); return; }
      top.forEach((p, i) => {
        const item = el('div', { class: 'tp-item' });
        item.innerHTML = `
          <span class="tp-rank">${i + 1}</span>
          <img class="tp-img" loading="lazy" src="${safeURL(p.image_url) || ''}" alt="${escapeHTML(p.name)}" onerror="this.style.visibility='hidden'"/>
          <div class="tp-info"><div class="tp-name">${escapeHTML(p.name)}</div><div class="tp-cat">${escapeHTML(CATEGORY_MAP[p.product_category] || '')}</div></div>
          <span class="tp-revenue">${Fmt.money(p.price)}</span>`;
        list.appendChild(item);
      });
    },
  };

  /* ==============================================================
     SEARCH + FILTER MODULES (shared helpers)
     ============================================================== */
  const Search = { attach(input, handler, wait = 250) { if (input) on(input, 'input', debounce((e) => handler(sanitizeInput(e.target.value)), wait)); } };
  const Filter = {
    attachTabs(container, handler) {
      if (!container) return;
      on(container, 'click', (e) => {
        const tab = e.target.closest('.ftab'); if (!tab) return;
        $$('.ftab', container).forEach((t) => t.classList.remove('on'));
        tab.classList.add('on'); handler(tab.dataset.value || 'all');
      });
    },
  };

  /* ==============================================================
     PRODUCTS MODULE
     ============================================================== */
  const ProductsModule = {
    state: { all: [], filtered: [], category: 'all', query: '', sort: 'newest', view: 'grid' },
    paginator: new Paginator({ pageSize: 12 }),
    async init() {
      this.cacheDom();
      this.bind();
      this.state.view = Storage.prefs.get('productView', 'grid');
      await this.load();
    },
    cacheDom() {
      this.dom = {
        grid: $('#admin-prod-grid'), tbody: $('#products-tbody'),
        count: $('#prod-count-label'), pagination: $('#products-pagination'),
        search: $('#product-search'), tabs: $('#product-filter-tabs'),
        sort: $('#product-sort'), viewToggle: $('#view-toggle'),
      };
    },
    bind() {
      Search.attach(this.dom.search, (q) => { this.state.query = q.toLowerCase(); this.apply(); });
      Filter.attachTabs(this.dom.tabs, (cat) => { this.state.category = cat; this.apply(); });
      on(this.dom.sort, 'change', (e) => { this.state.sort = e.target.value; this.apply(); });
      $$('[data-view]').forEach((b) => on(b, 'click', () => this.setView(b.dataset.view)));
      $$('[data-open-product]').forEach((b) => on(b, 'click', () => ProductEditor.open()));
      // event delegation for card/row actions
      on(document, 'click', (e) => {
        const editBtn = e.target.closest('[data-edit-product]');
        if (editBtn) { const p = this.state.all.find((x) => x.id == editBtn.dataset.editProduct); ProductEditor.open(p); }
      });
      on($('#products-export'), 'click', () => this.exportCSV());
    },
    async load() {
      this.renderSkeleton();
      try {
        const products = await API.products();
        this.state.all = products;
        Store.set('products', products); Store.cacheSet('products', products);
        this.apply();
      } catch (e) {
        Log.warn('products load', e.message);
        this.state.all = Store.get('products') || [];
        if (this.state.all.length) this.apply();
        else this.renderEmpty(e.status === 401 ? 'Sign in to manage products' : 'Unable to load products');
      }
    },
    apply() {
      let list = [...this.state.all];
      if (this.state.category !== 'all') list = list.filter((p) => p.product_category === this.state.category);
      if (this.state.query) list = list.filter((p) => `${p.name} ${p.description || ''}`.toLowerCase().includes(this.state.query));
      list = this.sortList(list);
      this.state.filtered = list;
      this.paginator.setTotal(list.length);
      this.render();
      this.updateCount();
    },
    sortList(list) {
      const s = this.state.sort;
      const by = { newest: (a, b) => b.id - a.id, oldest: (a, b) => a.id - b.id, 'price-hi': (a, b) => b.price - a.price, 'price-lo': (a, b) => a.price - b.price, name: (a, b) => (a.name || '').localeCompare(b.name || '') };
      return list.sort(by[s] || by.newest);
    },
    setView(view) {
      this.state.view = view; Storage.prefs.set('productView', view);
      $$('[data-view]').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
      this.render();
    },
    render() {
      const page = this.paginator.slice(this.state.filtered);
      if (!page.length) { this.renderEmpty(this.state.query || this.state.category !== 'all' ? 'No products match your filters' : 'No products yet'); return; }
      if (this.dom.grid) { this.dom.grid.classList.toggle('hidden', this.state.view !== 'grid'); if (this.state.view === 'grid') this.renderGrid(page); }
      const tableWrap = $('#products-table-wrap');
      if (tableWrap) tableWrap.classList.toggle('hidden', this.state.view !== 'list');
      if (this.dom.tbody && this.state.view === 'list') this.renderTable(page);
      this.paginator.render(this.dom.pagination, () => this.render());
      refreshIcons();
    },
    renderGrid(page) {
      const g = this.dom.grid; clear(g);
      page.forEach((p) => {
        const card = el('div', { class: 'product-card' });
        const inv = this.invState(p);
        card.innerHTML = `
          <div class="pac-img">
            <img loading="lazy" src="${safeURL(p.image_url) || ''}" alt="${escapeHTML(p.name)}" onerror="this.style.visibility='hidden'"/>
            <div class="pac-badges">${p.badge ? `<span class="badge no-dot ${(p.badge || '').toLowerCase()}">${escapeHTML(p.badge)}</span>` : ''}</div>
            <div class="pac-overlay">
              <button class="btn btn-sm btn-primary" data-edit-product="${p.id}"><i data-lucide="pencil"></i>Edit</button>
            </div>
          </div>
          <div class="pac-body">
            <div class="pac-cat">${escapeHTML(CATEGORY_MAP[p.product_category] || '')}</div>
            <div class="pac-name truncate">${escapeHTML(p.name)}</div>
            <div class="pac-price">${Fmt.money(p.price)}${p.old_price ? `<span class="old">${Fmt.money(p.old_price)}</span>` : ''}</div>
            <div class="pac-foot">
              <span class="badge no-dot ${inv.cls}">${inv.label}</span>
              <span class="fs-xs text-muted">Qty: ${Fmt.number(p.quantity)}</span>
            </div>
          </div>`;
        g.appendChild(card);
      });
    },
    renderTable(page) {
      const b = this.dom.tbody; clear(b);
      page.forEach((p) => {
        const inv = this.invState(p);
        const tr = el('tr');
        tr.innerHTML = `
          <td><input type="checkbox" class="row-check" data-id="${p.id}"/></td>
          <td><div class="cell-product"><img class="cell-thumb" loading="lazy" src="${safeURL(p.image_url) || ''}" alt="" onerror="this.style.visibility='hidden'"/><span class="td-strong truncate">${escapeHTML(p.name)}</span></div></td>
          <td class="td-mono">SKU-${String(p.id).padStart(4, '0')}</td>
          <td>${escapeHTML(CATEGORY_MAP[p.product_category] || '')}</td>
          <td class="td-strong">${Fmt.money(p.price)}</td>
          <td><span class="inventory-badge ${inv.cls}"><span class="qty">${Fmt.number(p.quantity)}</span></span></td>
          <td><span class="badge no-dot ${p.is_featured ? 'active' : 'neutral'}">${p.is_featured ? 'Featured' : 'Active'}</span></td>
          <td class="text-muted fs-xs">${Fmt.date(p.created_at)}</td>
          <td><div class="row-actions">
            <button class="icon-btn tooltip" data-tip="Edit" data-edit-product="${p.id}"><i data-lucide="pencil"></i></button>
          </div></td>`;
        b.appendChild(tr);
      });
    },
    invState(p) {
      const q = Number(p.quantity || 0);
      if (q <= 0) return { cls: 'out', label: 'Out of stock' };
      if (q <= 5) return { cls: 'low', label: 'Low stock' };
      return { cls: 'instock', label: 'In stock' };
    },
    updateCount() {
      if (!this.dom.count) return;
      const cats = new Set(this.state.all.map((p) => p.product_category)).size;
      this.dom.count.textContent = `${this.state.filtered.length} of ${this.state.all.length} products · ${cats} categories`;
      // KPI overview cards on products page
      const lows = this.state.all.filter((p) => Number(p.quantity) > 0 && Number(p.quantity) <= 5).length;
      const outs = this.state.all.filter((p) => Number(p.quantity) <= 0).length;
      this.setKpi('pkpi-total', this.state.all.length);
      this.setKpi('pkpi-active', this.state.all.filter((p) => Number(p.quantity) > 0).length);
      this.setKpi('pkpi-low', lows);
      this.setKpi('pkpi-out', outs);
      this.setKpi('pkpi-featured', this.state.all.filter((p) => p.is_featured).length);
      this.setKpi('pkpi-cats', cats);
      InventoryModule.render(this.state.all);
    },
    setKpi(id, v) { const n = document.getElementById(id); if (n) n.textContent = Fmt.number(v); },
    renderSkeleton() {
      const g = this.dom.grid; if (!g || this.state.view !== 'grid') return;
      clear(g);
      for (let i = 0; i < 6; i++) g.appendChild(el('div', { class: 'product-card', html: '<div class="pac-img skeleton"></div><div class="pac-body"><div class="skeleton skeleton-text short"></div><div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text short"></div></div>' }));
    },
    renderEmpty(msg) {
      const target = this.state.view === 'grid' ? this.dom.grid : this.dom.tbody;
      if (!target) return;
      if (target.tagName === 'TBODY') target.innerHTML = `<tr><td colspan="9">${UI.empty('package', msg, 'Add your first product to get started.')}</td></tr>`;
      else target.innerHTML = UI.empty('package', msg, 'Add your first product to get started.');
      if (this.dom.pagination) clear(this.dom.pagination);
      refreshIcons();
    },
    exportCSV() {
      const rows = this.state.filtered.map((p) => ({ id: p.id, name: p.name, category: p.product_category, price: p.price, quantity: p.quantity, featured: p.is_featured }));
      Exporter.toCSV(rows, `rtr-products-${Date.now()}.csv`);
    },
  };

  /* ==============================================================
     PRODUCT IMAGE UPLOAD + DRAG & DROP MODULE
     ============================================================== */
  const ImageUpload = {
    files: [], primary: 0,
    init(zoneId, previewId) {
      this.zone = document.getElementById(zoneId);
      this.preview = document.getElementById(previewId);
      this.files = []; this.primary = 0;
      if (!this.zone) return;
      const input = $('input[type="file"]', this.zone);
      on(input, 'change', (e) => this.add(e.target.files));
      ['dragenter', 'dragover'].forEach((ev) => on(this.zone, ev, (e) => { e.preventDefault(); this.zone.classList.add('dragover'); }));
      ['dragleave', 'drop'].forEach((ev) => on(this.zone, ev, (e) => { e.preventDefault(); this.zone.classList.remove('dragover'); }));
      on(this.zone, 'drop', (e) => this.add(e.dataTransfer.files));
    },
    add(fileList) {
      const allowed = ['image/jpeg', 'image/png', 'image/webp', 'image/avif'];
      Array.from(fileList).forEach((f) => {
        if (!allowed.includes(f.type)) { Notify.warning(`${f.name}: unsupported format`); return; }
        if (f.size > 8 * 1024 * 1024) { Notify.warning(`${f.name}: exceeds 8MB`); return; }
        this.files.push(f);
      });
      this.render();
    },
    render() {
      if (!this.preview) return;
      clear(this.preview);
      this.files.forEach((f, i) => {
        const url = URL.createObjectURL(f);
        const item = el('div', { class: `image-preview-item ${i === this.primary ? 'primary' : ''}` });
        item.innerHTML = `${i === this.primary ? '<span class="primary-tag">Primary</span>' : ''}<img src="${url}" alt="${escapeHTML(f.name)}"/><div class="ip-actions"><button class="icon-btn tooltip" data-tip="Set primary" type="button" data-primary="${i}"><i data-lucide="star"></i></button><button class="icon-btn danger tooltip" data-tip="Remove" type="button" data-remove="${i}"><i data-lucide="trash-2"></i></button></div>`;
        on($('[data-primary]', item), 'click', () => { this.primary = i; this.render(); });
        on($('[data-remove]', item), 'click', () => { this.files.splice(i, 1); if (this.primary >= this.files.length) this.primary = 0; this.render(); });
        this.preview.appendChild(item);
      });
      refreshIcons();
    },
    primaryFile() { return this.files[this.primary] || null; },
    reset() { this.files = []; this.primary = 0; this.render(); },
  };

  /* ==============================================================
     PRODUCT EDITOR MODULE (modal CRUD)
     ============================================================== */
  const ProductEditor = {
    editing: null,
    init() {
      this.modal = $('#product-modal');
      if (!this.modal) return;
      ImageUpload.init('pm-upload-zone', 'pm-image-preview');
      on($('#pm-save'), 'click', () => this.save());
      on($('#pm-delete'), 'click', () => this.deleteProduct());
      // live margin display
      ['pm-price', 'pm-cost'].forEach((id) => on(document.getElementById(id), 'input', () => this.updateMargin()));
    },
    open(product = null) {
      if (!this.modal) { Notify.info('Product editor is available on the Products page.'); return; }
      this.editing = product;
      $('#pm-modal-title').textContent = product ? 'Edit Product' : 'Add Product';
      const set = (id, v) => { const n = document.getElementById(id); if (n) n.value = v ?? ''; };
      set('pm-name', product?.name);
      set('pm-cat', product?.product_category || '');
      set('pm-price', product?.price);
      set('pm-old-price', product?.old_price);
      set('pm-quantity', product?.quantity);
      set('pm-badge', product?.badge || '');
      set('pm-desc', product?.description);
      const feat = $('#pm-featured'); if (feat) feat.checked = !!product?.is_featured;
      ImageUpload.reset();
      $$('.field-error', this.modal).forEach((n) => n.remove());
      this.updateMargin();
      const delBtn = $('#pm-delete'); if (delBtn) delBtn.classList.toggle('hidden', !product);
      Modal.open('product-modal');
    },
    updateMargin() {
      const price = Number($('#pm-price')?.value || 0);
      const cost = Number($('#pm-cost')?.value || 0);
      const disp = $('#pm-margin'); if (!disp) return;
      if (price > 0 && cost > 0) { const m = ((price - cost) / price) * 100; disp.textContent = `Margin: ${m.toFixed(1)}%`; disp.classList.remove('hidden'); }
      else disp.classList.add('hidden');
    },
    validate() {
      let ok = true;
      const fail = (id, msg) => { ok = false; const f = document.getElementById(id); if (!f) return; f.classList.add('input-error'); if (!f.parentElement.querySelector('.field-error')) f.parentElement.appendChild(el('span', { class: 'field-error', text: msg })); };
      $$('.field-error', this.modal).forEach((n) => n.remove());
      $$('.input-error', this.modal).forEach((n) => n.classList.remove('input-error'));
      if (!Validate.required($('#pm-name').value)) fail('pm-name', 'Name is required');
      if (!Validate.positive($('#pm-price').value)) fail('pm-price', 'Enter a valid price');
      if (!Validate.required($('#pm-cat').value)) fail('pm-cat', 'Choose a category');
      if (!Validate.nonNegative($('#pm-quantity').value)) fail('pm-quantity', 'Enter quantity');
      if (!this.editing && !ImageUpload.primaryFile()) { Notify.warning('Please upload at least one product image.'); ok = false; }
      return ok;
    },
    async save() {
      if (!this.validate()) return;
      const fd = new FormData();
      fd.append('name', sanitizeInput($('#pm-name').value, 255));
      fd.append('price', Number($('#pm-price').value));
      fd.append('quantity', Number($('#pm-quantity').value || 0));
      fd.append('product_category', $('#pm-cat').value);
      fd.append('description', sanitizeInput($('#pm-desc').value, 4000));
      fd.append('is_featured', $('#pm-featured')?.checked ? 'true' : 'false');
      const file = ImageUpload.primaryFile();
      if (file) fd.append('file', file);
      const btn = $('#pm-save'); const orig = btn.innerHTML;
      btn.disabled = true; btn.innerHTML = '<span class="spinner spinner-sm"></span> Saving…';
      try {
        if (this.editing) await API.updateProduct(this.editing.id, fd);
        else await API.createProduct(fd);
        Notify.success(this.editing ? 'Product updated' : 'Product created');
        Modal.close('product-modal');
        Store.invalidate('products');
        await ProductsModule.load();
      } catch (e) {
        Log.error('save product', e);
        Notify.error(e.message || 'Failed to save product');
      } finally { btn.disabled = false; btn.innerHTML = orig; }
    },
    async deleteProduct() {
      if (!this.editing) return;
      const name = this.editing.name || 'this product';
      if (!confirm(`Delete "${name}"? This action cannot be undone.`)) return;
      const btn = $('#pm-delete'); const orig = btn.innerHTML;
      btn.disabled = true; btn.innerHTML = '<span class="spinner spinner-sm"></span> Deleting…';
      try {
        await API.deleteProduct(this.editing.id);
        Notify.success('Product deleted');
        Modal.close('product-modal');
        Store.invalidate('products');
        await ProductsModule.load();
      } catch (e) {
        Log.error('delete product', e);
        Notify.error(e.message || 'Failed to delete product');
      } finally { btn.disabled = false; btn.innerHTML = orig; }
    },
  };

  /* ==============================================================
     INVENTORY MODULE
     ============================================================== */
  const InventoryModule = {
    render(products = []) {
      const wrap = $('#inventory-alerts'); if (!wrap) return;
      const low = products.filter((p) => Number(p.quantity) > 0 && Number(p.quantity) <= 5);
      const out = products.filter((p) => Number(p.quantity) <= 0);
      const alerts = [...out.map((p) => ({ p, type: 'out' })), ...low.map((p) => ({ p, type: 'low' }))].slice(0, 8);
      clear(wrap);
      if (!alerts.length) { wrap.innerHTML = UI.empty('check-circle', 'Inventory healthy', 'No low or out-of-stock items.'); refreshIcons(); return; }
      alerts.forEach(({ p, type }) => {
        const item = el('div', { class: 'inventory-alert-item' });
        item.innerHTML = `
          <img class="ia-thumb" loading="lazy" src="${safeURL(p.image_url) || ''}" alt="" onerror="this.style.visibility='hidden'"/>
          <div class="ia-info"><div class="ia-name truncate">${escapeHTML(p.name)}</div><div class="ia-meta">${CATEGORY_MAP[p.product_category] || ''} · Qty ${Fmt.number(p.quantity)}</div></div>
          <span class="badge no-dot ${type}">${type === 'out' ? 'Out of stock' : 'Low stock'}</span>`;
        wrap.appendChild(item);
      });
      refreshIcons();
    },
  };

  /* ==============================================================
     ORDERS MODULE
     ============================================================== */
  const OrdersModule = {
    state: { all: [], filtered: [], status: 'all', query: '' },
    async init() {
      this.tbody = $('#orders-tbody') || $('#orders-body');
      this.bind();
      await this.load();
    },
    bind() {
      Search.attach($('#order-search'), (q) => { this.state.query = q.toLowerCase(); this.apply(); });
      Filter.attachTabs($('#order-filter-tabs'), (s) => { this.state.status = s; this.apply(); });
      on($('#orders-export'), 'click', () => this.exportCSV());
      on(document, 'click', (e) => {
        const view = e.target.closest('[data-view-order]');
        if (view) { const o = this.state.all.find((x) => x.id == view.dataset.viewOrder); if (o) this.openDetail(o); }
        const act = e.target.closest('[data-order-action]');
        if (act) this.confirmAction(act.dataset.orderId, act.dataset.orderAction);
      });
    },
    async load() {
      if (!this.tbody) return;
      this.renderSkeleton();
      try {
        const orders = await API.orders({ limit: 100 });
        this.state.all = orders; Store.set('orders', orders);
        this.apply();
      } catch (e) {
        Log.warn('orders load', e.message);
        Notify.error(`Couldn't load full order list: ${e.message || 'unknown error'}`);
        // Fall back to whatever the dashboard widget already fetched successfully,
        // so "View" on those rows still works even though this larger fetch failed.
        const cached = Store.get('orders') || [];
        if (cached.length) { this.state.all = cached; this.apply(); }
        else {
          this.tbody.innerHTML = `<tr><td colspan="10">${UI.empty('shopping-bag', e.status === 401 ? 'Sign in to view orders' : 'Unable to load orders', '')}</td></tr>`;
          refreshIcons();
        }
      }
    },
    apply() {
      let list = [...this.state.all];
      if (this.state.status !== 'all') list = list.filter((o) => (o.status || '').toLowerCase() === this.state.status);
      if (this.state.query) list = list.filter((o) => `${o.order_reference || o.id} ${o.customer_email || ''} ${o.customer_phone || ''}`.toLowerCase().includes(this.state.query));
      this.state.filtered = list;
      this.render();
    },
    render() {
      const b = this.tbody; if (!b) return; clear(b);
      if (!this.state.filtered.length) { b.innerHTML = `<tr><td colspan="10">${UI.empty('shopping-bag', 'No orders found', '')}</td></tr>`; refreshIcons(); return; }
      this.state.filtered.forEach((o) => b.appendChild(this.fullRow(o)));
      refreshIcons();
    },
    renderSkeleton() {
      const b = this.tbody; if (!b) return;
      clear(b);
      for (let i = 0; i < 6; i++) {
        const tr = el('tr');
        tr.innerHTML = `
          <td><div class="skeleton skeleton-text short"></div></td>
          <td><div class="skeleton skeleton-text"></div></td>
          <td><div class="skeleton skeleton-text"></div></td>
          <td><div class="skeleton skeleton-text short"></div></td>
          <td><div class="skeleton skeleton-text short"></div></td>
          <td class="hide-mobile"><div class="skeleton skeleton-text"></div></td>
          <td class="hide-mobile"><div class="skeleton skeleton-text short"></div></td>
          <td><div class="skeleton skeleton-text short"></div></td>
          <td><div class="skeleton skeleton-text short"></div></td>
          <td></td>`;
        b.appendChild(tr);
      }
    },
    fullRow(o) {
      const tr = el('tr');
      const item = (o.items && o.items[0]) || {};
      const qty = (o.items || []).reduce((s, i) => s + (i.quantity || 0), 0) || item.quantity || 1;
      tr.innerHTML = `
        <td class="td-mono">${escapeHTML(o.order_reference || `#${o.id}`)}</td>
        <td><div class="customer-row"><span class="customer-avatar">${Fmt.initials(o.customer_email || 'NA')}</span><div><div class="customer-name truncate">${escapeHTML(o.customer_email || '—')}</div></div></div></td>
        <td class="truncate" style="max-width:180px">${escapeHTML(item.product_name_snapshot || (o.items?.length ? `${o.items.length} items` : '—'))}</td>
        <td>${qty}</td>
        <td class="td-strong">${Fmt.money(o.total_amount)}</td>
        <td class="truncate hide-mobile" style="max-width:160px">${escapeHTML(o.shipping_address || '—')}</td>
        <td class="hide-mobile">${escapeHTML(o.customer_phone || '—')}</td>
        <td class="text-muted fs-xs">${Fmt.date(o.created_at)}</td>
        <td><span class="badge ${(o.status || 'pending').toLowerCase()}">${Fmt.titleCase(o.status || 'pending')}</span><div class="fs-xs text-muted mt-1">${this.channelLabel(o.payment_method)}</div></td>
        <td><div class="row-actions"><button type="button" class="icon-btn tooltip" data-tip="View" data-view-order="${o.id}" onclick="window.RTR_viewOrder(${o.id})"><i data-lucide="eye"></i></button></div></td>`;
      return tr;
    },
    compactRow(o) {
      const tr = el('tr');
      const item = (o.items && o.items[0]) || {};
      tr.innerHTML = `
        <td class="td-mono">${escapeHTML(o.order_reference || `#${o.id}`)}</td>
        <td class="truncate" style="max-width:150px">${escapeHTML(o.customer_email || '—')}</td>
        <td class="truncate" style="max-width:150px">${escapeHTML(item.product_name_snapshot || '—')}</td>
        <td class="td-strong">${Fmt.money(o.total_amount)}</td>
        <td class="text-muted fs-xs">${Fmt.date(o.created_at)}</td>
        <td><span class="badge ${(o.status || 'pending').toLowerCase()}">${Fmt.titleCase(o.status || 'pending')}</span><div class="fs-xs text-muted mt-1">${this.channelLabel(o.payment_method)}</div></td>
        <td><button type="button" class="icon-btn tooltip" data-tip="View" data-view-order="${o.id}" onclick="window.RTR_viewOrder(${o.id})"><i data-lucide="eye"></i></button></td>`;
      return tr;
    },
    emptyRow(msg) { return UI.empty('shopping-bag', msg, ''); },
    channelLabel(method) { return (method || '').toLowerCase() === 'whatsapp' ? 'via WhatsApp' : 'via Paystack'; },
    openDetail(o) {
      const modal = $('#order-modal'); if (!modal) { Notify.info(`Order ${o.order_reference || o.id}`); return; }
      $('#om-title').textContent = `Order ${o.order_reference || '#' + o.id}`;
      const body = $('#om-body');
      const items = (o.items || []).map((i) => `
        <div class="order-item-line">
          <img class="oil-thumb" loading="lazy" src="${safeURL(i.product_image_snapshot) || ''}" alt="" onerror="this.style.visibility='hidden'"/>
          <div class="oil-info"><div class="oil-name truncate">${escapeHTML(i.product_name_snapshot || 'Item')}</div><div class="oil-meta">Qty ${i.quantity} · ${Fmt.money(i.unit_price_at_purchase)}${i.is_customized ? ' · Custom' : ''}</div></div>
          <span class="oil-price">${Fmt.money((i.unit_price_at_purchase || 0) * (i.quantity || 1))}</span>
        </div>`).join('') || '<p class="text-muted fs-sm">No line items recorded.</p>';
      body.innerHTML = `
        <div class="info-row"><span class="info-label">Status</span><span class="info-value"><span class="badge ${(o.status || 'pending').toLowerCase()}">${Fmt.titleCase(o.status || 'pending')}</span></span></div>
        <div class="info-row"><span class="info-label">Channel</span><span class="info-value">${(o.payment_method || '').toLowerCase() === 'whatsapp' ? 'WhatsApp' : 'Paystack'}</span></div>
        <div class="info-row"><span class="info-label">Customer</span><span class="info-value">${escapeHTML(o.customer_email || '—')}</span></div>
        <div class="info-row"><span class="info-label">Phone</span><span class="info-value">${escapeHTML(o.customer_phone || '—')}</span></div>
        <div class="info-row"><span class="info-label">Shipping</span><span class="info-value">${escapeHTML(o.shipping_address || '—')}</span></div>
        <div class="info-row"><span class="info-label">Payment Ref</span><span class="info-value">${escapeHTML(o.payment_reference || '—')}</span></div>
        <div class="info-row"><span class="info-label">Total</span><span class="info-value td-strong">${Fmt.money(o.total_amount)}</span></div>
        <div class="divider"></div><div class="card-title mb-1">Items</div>${items}
        <div class="divider"></div>
        <div class="form-group"><label>Fulfillment note (emailed to customer)</label><textarea id="om-note" placeholder="e.g. Your order has shipped via GIG Logistics, tracking #…">${escapeHTML(o.fulfillment_note || '')}</textarea></div>`;
      const foot = $('#om-foot');
      const st = (o.status || 'pending').toLowerCase();
      let actions = '';
      if (st === 'pending') {
        actions = `
          <button class="btn btn-danger" data-order-action="cancel" data-order-id="${o.id}"><i data-lucide="x"></i>Cancel</button>
          <button class="btn btn-success" data-order-action="confirm" data-order-id="${o.id}"><i data-lucide="check"></i>Confirm Order</button>`;
      } else if (st === 'paid' || st === 'processing') {
        actions = `
          <button class="btn btn-danger" data-order-action="cancel" data-order-id="${o.id}"><i data-lucide="x"></i>Cancel</button>
          <button class="btn btn-ghost" data-order-action="ship" data-order-id="${o.id}"><i data-lucide="truck"></i>Mark Shipped</button>
          <button class="btn btn-success" data-order-action="complete" data-order-id="${o.id}"><i data-lucide="check"></i>Complete</button>`;
      } else if (st === 'shipped') {
        actions = `<button class="btn btn-success" data-order-action="complete" data-order-id="${o.id}"><i data-lucide="check"></i>Mark Delivered</button>`;
      } else {
        actions = `<p class="text-muted fs-sm">This order is ${Fmt.titleCase(st)} — no further actions available.</p>`;
      }
      foot.innerHTML = actions;
      Modal.open('order-modal');
      refreshIcons();
    },
    async confirmAction(id, action) {
      const labels = { confirm: 'confirm', cancel: 'cancel', complete: 'complete', reject: 'reject', ship: 'mark as shipped' };
      const note = $('#om-note')?.value || '';
      if (!confirm(`Are you sure you want to ${labels[action] || action} this order?`)) return;
      try {
        await API.orderAction(id, action, sanitizeInput(note, 2000));
        Notify.success(`Order ${labels[action] || action} done`);
        Modal.close('order-modal');
        await this.load();
      } catch (e) { Notify.error(e.message || 'Action failed'); }
    },
    exportCSV() {
      const rows = this.state.filtered.map((o) => ({ reference: o.order_reference || o.id, email: o.customer_email, phone: o.customer_phone, total: o.total_amount, status: o.status, date: o.created_at }));
      Exporter.toCSV(rows, `rtr-orders-${Date.now()}.csv`);
    },
  };

  /* ==============================================================
     CUSTOMERS MODULE
     ============================================================== */
  const CustomersModule = {
    state: { all: [], query: '' },
    async init() {
      this.tbody = $('#customers-tbody');
      Search.attach($('#customer-search'), (q) => { this.state.query = q.toLowerCase(); this.render(); });
      on(document, 'click', (e) => {
        const ban = e.target.closest('[data-ban]'); if (ban) this.moderate(ban.dataset.ban, ban.dataset.banned === 'true' ? 'unban' : 'ban');
      });
      await this.load();
    },
    async load() {
      if (!this.tbody && !$('#recent-customers')) return;
      try { const users = await API.users({ limit: 100 }); this.state.all = users; Store.set('customers', users); this.render(); this.renderRecent(users); }
      catch (e) { Log.warn('customers', e.message); if (this.tbody) { this.tbody.innerHTML = `<tr><td colspan="6">${UI.empty('users', 'Unable to load customers', '')}</td></tr>`; refreshIcons(); } }
    },
    filtered() { return this.state.query ? this.state.all.filter((u) => `${u.full_name || ''} ${u.email}`.toLowerCase().includes(this.state.query)) : this.state.all; },
    render() {
      if (!this.tbody) return; clear(this.tbody);
      const list = this.filtered();
      if (!list.length) { this.tbody.innerHTML = `<tr><td colspan="6">${UI.empty('users', 'No customers found', '')}</td></tr>`; refreshIcons(); return; }
      list.forEach((u) => {
        const tr = el('tr');
        tr.innerHTML = `
          <td><div class="customer-row"><span class="customer-avatar">${Fmt.initials(u.full_name || u.email)}</span><div><div class="customer-name">${escapeHTML(u.full_name || '—')}</div><div class="customer-email">${escapeHTML(u.email)}</div></div></div></td>
          <td>${escapeHTML(u.country || '—')}</td>
          <td class="td-strong">${Fmt.money(u.balance)}</td>
          <td><span class="badge no-dot ${u.is_verified ? 'active' : 'draft'}">${u.is_verified ? 'Verified' : 'Pending'}</span></td>
          <td><span class="badge no-dot ${u.is_banned ? 'danger' : 'neutral'}">${u.is_banned ? 'Banned' : 'Active'}</span></td>
          <td><button class="btn btn-xs ${u.is_banned ? 'btn-success' : 'btn-danger'}" data-ban="${u.id}" data-banned="${u.is_banned}">${u.is_banned ? 'Unban' : 'Ban'}</button></td>`;
        this.tbody.appendChild(tr);
      });
      refreshIcons();
    },
    renderRecent(users) {
      const wrap = $('#recent-customers'); if (!wrap) return; clear(wrap);
      users.slice(0, 5).forEach((u) => {
        const item = el('div', { class: 'activity-item' });
        item.innerHTML = `<span class="customer-avatar">${Fmt.initials(u.full_name || u.email)}</span><div class="activity-body"><div class="activity-text"><strong>${escapeHTML(u.full_name || u.email)}</strong></div><div class="activity-time">${escapeHTML(u.country || '')} · ${Fmt.relative(u.created_at)}</div></div>`;
        wrap.appendChild(item);
      });
    },
    async moderate(id, action) {
      if (!confirm(`${action === 'ban' ? 'Ban' : 'Unban'} this customer?`)) return;
      try { await (action === 'ban' ? API.banUser(id) : API.unbanUser(id)); Notify.success(`Customer ${action}ned`); await this.load(); }
      catch (e) { Notify.error(e.message || 'Action failed'); }
    },
  };

  /* ==============================================================
     HERO BANNER + FLOATING IMAGE MODULE
     ============================================================== */
  const HeroModule = {
    _file: null,        // staged hero background File, if any
    _floatFiles: [],     // staged (unsaved) floating-image Files awaiting upload
    _floatBanners: [],   // persisted floating banners fetched from the backend
    init() {
      this.bindPreview();
      this.bindUpload();
      this.bindFloatingImages();
      on($('#hero-save'), 'click', () => this.save());
      on($('#banner-list'), 'click', (e) => {
        const delBtn = e.target.closest('[data-delete-banner]');
        if (delBtn) this.deleteBanner(delBtn.dataset.deleteBanner, delBtn);
      });
      on($('#float-img-list'), 'click', (e) => {
        const removeDraft = e.target.closest('[data-remove-draft]');
        if (removeDraft) { this._floatFiles.splice(Number(removeDraft.dataset.removeDraft), 1); this.renderFloatingImages(); return; }
        const delFloat = e.target.closest('[data-delete-float]');
        if (delFloat) this.deleteBanner(delFloat.dataset.deleteFloat, delFloat);
      });
      this.loadBanners();
    },
    bindPreview() {
      const map = { 'hero-h1': 'prev-title', 'hero-h2': 'prev-title-em', 'hero-sub': 'prev-sub' };
      Object.entries(map).forEach(([src, dest]) => {
        const input = document.getElementById(src);
        on(input, 'input', () => { const d = document.getElementById(dest); if (d) d.textContent = sanitizeInput(input.value, 200); });
      });
    },
    /* ---- Hero upload zone visual state ---------------------------- */
    _setUploadZoneState(active, label) {
      const zone = $('#hero-upload-zone'); if (!zone) return;
      const icon = $('.uz-icon i', zone);
      const text = $('p', zone);
      zone.classList.toggle('has-file', active);
      zone.style.borderColor = active ? 'var(--accent, #C4956A)' : '';
      zone.style.background = active ? 'rgba(196,149,106,.08)' : '';
      if (icon) icon.setAttribute('data-lucide', active ? 'check-circle' : 'image-plus');
      if (text) text.textContent = active ? label : 'Click or drop a hero background';
      refreshIcons();
    },
    bindUpload() {
      const input = $('#hero-bg-input');
      on(input, 'change', (e) => {
        const f = e.target.files[0]; if (!f) return;
        const img = $('#hero-bg-preview'); if (img) img.src = URL.createObjectURL(f);
        this._file = f;
        this._setUploadZoneState(true, `Selected: ${f.name}`);
      });
      on($('#hero-bg-url-apply'), 'click', () => {
        const url = safeURL($('#hero-bg-url')?.value);
        if (!url) { Notify.warning('Enter a valid image URL'); return; }
        const img = $('#hero-bg-preview'); if (img) img.src = url;
        this._file = null; // an explicitly applied URL takes precedence over a previously picked file
      });
    },
    /* ---- Floating images: staging + persistence -------------------- */
    bindFloatingImages() {
      const trigger = $('#add-float-img');
      const input = $('#float-img-input');
      on(trigger, 'click', () => input && input.click());
      on(input, 'change', (e) => {
        const files = Array.from(e.target.files || []);
        if (!files.length) return;
        this._floatFiles.push(...files);
        this.renderFloatingImages();
        input.value = ''; // allow re-selecting the same file(s) later
      });
      on($('#save-float-img'), 'click', () => this.saveFloatingImages());
    },
    renderFloatingImages() {
      const wrap = $('#float-img-list'); if (!wrap) return;
      clear(wrap);
      if (!this._floatFiles.length && !this._floatBanners.length) {
        wrap.innerHTML = UI.empty('image-plus', 'No floating images', 'Add images to display them floating around the hero.');
        refreshIcons(); return;
      }
      this._floatFiles.forEach((f, i) => {
        f.__previewUrl = f.__previewUrl || URL.createObjectURL(f);
        const item = el('div', { class: 'float-img-item' });
        item.innerHTML = `
          <img src="${f.__previewUrl}" alt="${escapeHTML(f.name)}"/>
          <span class="badge no-dot draft">Unsaved Draft</span>
          <div class="fi-actions"><button class="icon-btn danger tooltip" data-tip="Remove" type="button" data-remove-draft="${i}"><i data-lucide="trash-2"></i></button></div>`;
        wrap.appendChild(item);
      });
      this._floatBanners.forEach((b) => {
        const item = el('div', { class: 'float-img-item' });
        item.innerHTML = `
          <img loading="lazy" src="${safeURL(b.image_url) || ''}" alt="${escapeHTML(b.title || 'Floating image')}" onerror="this.style.visibility='hidden'"/>
          <div class="fi-actions"><button class="icon-btn danger tooltip" data-tip="Delete" type="button" data-delete-float="${b.id}"><i data-lucide="trash-2"></i></button></div>`;
        wrap.appendChild(item);
      });
      refreshIcons();
    },
    async saveFloatingImages() {
      if (!this._floatFiles.length) { Notify.warning('Add at least one image before saving'); return; }
      const btn = $('#save-float-img'); const orig = btn.innerHTML;
      btn.disabled = true; btn.innerHTML = '<span class="spinner spinner-sm"></span> Saving…';

      const remaining = [];
      let successCount = 0, failCount = 0;
      for (const f of this._floatFiles) {
        try {
          const fd = new FormData();
          fd.append('file', f);
          fd.append('section_type', 'floating');
          fd.append('title', f.name);
          fd.append('is_active', 'true');
          await API.createBanner(fd);
          successCount++;
        } catch (e) {
          Log.error('save floating image', f.name, e);
          failCount++;
          remaining.push(f);
        }
      }
      this._floatFiles = remaining;
      btn.disabled = false; btn.innerHTML = orig;

      if (successCount) {
        Notify.success(`${successCount} floating image${successCount > 1 ? 's' : ''} saved`);
        Store.invalidate('banners');
        await this.loadBanners(); // also re-renders the floating list
      } else {
        this.renderFloatingImages();
      }
      if (failCount) Notify.error(`${failCount} image${failCount > 1 ? 's' : ''} failed to upload`);
    },
    /* ---- Load + render everything from the backend ----------------- */
    async loadBanners() {
      const wrap = $('#banner-list'); if (!wrap) return;
      try {
        const banners = await API.banners(false);
        Store.set('banners', banners);

        const heroBanners = banners.filter((b) => b.section_type !== 'floating');
        this._floatBanners = banners.filter((b) => b.section_type === 'floating');

        clear(wrap);
        if (!heroBanners.length) { wrap.innerHTML = UI.empty('image', 'No banners yet', 'Upload a hero image to begin.'); }
        else {
          heroBanners.forEach((b) => {
            const card = el('div', { class: 'banner-card' });
            card.innerHTML = `
              <img class="banner-thumb" loading="lazy" src="${safeURL(b.image_url) || ''}" alt="" onerror="this.style.visibility='hidden'"/>
              <div class="flex-1">
                <div class="td-strong">${escapeHTML(b.title || Fmt.titleCase(b.section_type))}</div>
                <div class="fs-xs text-muted">${escapeHTML(b.section_type)}</div>
              </div>
              <span class="badge no-dot ${b.is_active ? 'active' : 'neutral'}">${b.is_active ? 'Active' : 'Hidden'}</span>
              <button class="icon-btn danger tooltip" data-tip="Delete banner" type="button" data-delete-banner="${b.id}"><i data-lucide="trash-2"></i></button>`;
            wrap.appendChild(card);
          });
        }
        refreshIcons();
        this.renderFloatingImages();
      } catch (e) {
        Log.warn('banners', e.message);
        wrap.innerHTML = UI.empty('image', 'Unable to load banners', '');
        refreshIcons();
      }
    },
    async save() {
      const url = safeURL($('#hero-bg-url')?.value || '');
      if (!this._file && !url) { Notify.warning('Please upload a banner image or provide an image URL.'); return; }

      const fd = new FormData();
      // Image: a physical file takes priority over a pasted URL.
      if (this._file) fd.append('file', this._file);
      else fd.append('image_url', url);

      fd.append('title', sanitizeInput($('#hero-h1')?.value, 255));
      fd.append('section_type', 'hero');
      fd.append('target_url', sanitizeInput($('#hero-target-url')?.value, 500));
      fd.append('display_order', String(Number($('#hero-display-order')?.value || 0)));
      fd.append('is_active', $('#hero-is-active') ? ($('#hero-is-active').checked ? 'true' : 'false') : 'true');

      const btn = $('#hero-save'); const orig = btn.innerHTML;
      btn.disabled = true; btn.innerHTML = '<span class="spinner spinner-sm"></span> Saving…';
      try {
        await API.createBanner(fd);
        Notify.success('Banner saved');
        // Presentational hero copy (eyebrow / sub / CTA label) isn't part of the
        // Banner schema, so it's retained as a local draft alongside the persisted banner.
        Storage.set('rtr_hero_draft', { h1: $('#hero-h1')?.value, h2: $('#hero-h2')?.value, sub: $('#hero-sub')?.value, cta: $('#hero-cta')?.value, eyebrow: $('#hero-eyebrow')?.value });
        this._file = null;
        const input = $('#hero-bg-input'); if (input) input.value = '';
        this._setUploadZoneState(false);
        Store.invalidate('banners');
        await this.loadBanners();
      } catch (e) {
        Log.error('save banner', e);
        Notify.error(e.message || 'Failed to save banner');
      } finally { btn.disabled = false; btn.innerHTML = orig; }
    },
    async deleteBanner(id, btn) {
      if (!confirm('Delete this banner? This action cannot be undone.')) return;
      if (btn) btn.disabled = true;
      try {
        await API.deleteBanner(id);
        Notify.success('Banner deleted');
        Store.invalidate('banners');
        await this.loadBanners();
      } catch (e) {
        Log.error('delete banner', e);
        Notify.error(e.message || 'Failed to delete banner');
        if (btn) btn.disabled = false;
      }
    },
  };

  /* ==============================================================
     SHARED UI SNIPPETS
     ============================================================== */
  const UI = {
    empty(icon, title, sub) {
      return `<div class="empty-state"><span class="es-icon"><i data-lucide="${icon}"></i></span><h4>${escapeHTML(title)}</h4>${sub ? `<p>${escapeHTML(sub)}</p>` : ''}</div>`;
    },
  };

  /* ==============================================================
     TABS + ACCORDION (generic UI controllers)
     ============================================================== */
  const TabController = {
    init() {
      on(document, 'click', (e) => {
        const tab = e.target.closest('.tab[data-tab]'); if (!tab) return;
        const group = tab.closest('.tabs');
        $$('.tab', group).forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');
        const panelId = tab.dataset.tab;
        const scope = group.parentElement;
        $$('.tab-panel', scope).forEach((p) => p.classList.toggle('active', p.id === panelId));
      });
    },
  };
  const AccordionController = {
    init() { on(document, 'click', (e) => { const head = e.target.closest('.accordion-head'); if (head) head.closest('.accordion-item').classList.toggle('open'); }); },
  };

  /* ==============================================================
     ERROR HANDLING MODULE (global)
     ============================================================== */
  const ErrorHandler = {
    init() {
      window.addEventListener('unhandledrejection', (e) => {
        Log.error('Unhandled rejection', e.reason);
        if (e.reason instanceof APIError && e.reason.status !== 401) Notify.error(e.reason.message);
      });
      window.addEventListener('error', (e) => { Log.error('Global error', e.message); });
    },
  };

  /* ==============================================================
     PROFILE / LOGOUT WIRING
     ============================================================== */
  const AccountUI = {
    init() {
      $$('[data-logout]').forEach((b) => on(b, 'click', (e) => { e.preventDefault(); Auth.logout(); }));
    },
  };

  /* ==============================================================
     BOOTSTRAP + INITIALIZATION
     ============================================================== */
  const PAGE_MODULES = {
    dashboard: [DashboardModule, AnalyticsModule, OrdersModule, CustomersModule],
    products: [ProductsModule, ProductEditor, OrdersModule, CustomersModule, InventoryModule],
    content: [HeroModule],
  };

  const App = {
    async init() {
      Log.time('boot');
      // Core (all pages) — each wrapped so one failure can't silently
      // block everything after it (including OrdersModule's bind()).
      const coreSteps = [
        ['Auth.hydrate', () => Auth.hydrate()],
        ['Modal.init', () => Modal.init()],
        ['Drawer.init', () => Drawer.init()],
        ['Dropdown.init', () => Dropdown.init()],
        ['Tooltip.init', () => Tooltip.init()],
        ['Nav.init', () => Nav.init()],
        ['Theme.init', () => Theme.init()],
        ['Shortcuts.init', () => Shortcuts.init()],
        ['ErrorHandler.init', () => ErrorHandler.init()],
        ['TabController.init', () => TabController.init()],
        ['AccordionController.init', () => AccordionController.init()],
        ['AccountUI.init', () => AccountUI.init()],
      ];
      for (const [name, fn] of coreSteps) {
        try { fn(); } catch (e) { Log.error(`Core init failed: ${name}`, e); }
      }
      refreshIcons();

      const page = document.body.dataset.page || 'dashboard';
      Log.info('Initializing page:', page);

     

      const modules = PAGE_MODULES[page] || [];
      for (const mod of modules) {
        try { await mod.init?.(); }
        catch (e) { Log.error(`Module init failed on ${page}`, e); }
      }

      refreshIcons();
      EventBus.emit('app:ready', page);
      Log.timeEnd('boot');
    },
  };

  // Expose a minimal namespace for debugging / inline hooks
  // Bulletproof direct handler — works even if OrdersModule's delegated
  // click listener never attached for some reason.
  window.RTR_viewOrder = async (id) => {
    try {
      const cached = (OrdersModule.state.all || []).find((x) => x.id == id)
        || (Store.get('orders') || []).find((x) => x.id == id);
      if (cached) { OrdersModule.openDetail(cached); return; }
      // Not cached anywhere yet — fetch it directly rather than doing nothing.
      const orders = await API.orders({ limit: 100 });
      const found = orders.find((x) => x.id == id);
      if (found) { OrdersModule.openDetail(found); }
      else { Notify.error(`Order #${id} not found.`); }
    } catch (e) {
      Notify.error(`Couldn't open order: ${e.message || 'unknown error'}`);
    }
  };

  window.RTR = Object.freeze({ API, Store, Auth, Notify, Modal, Drawer, EventBus, Fmt, CONFIG, Exporter, ProductEditor, ProductsModule, OrdersModule });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => App.init());
  else App.init();
})();
