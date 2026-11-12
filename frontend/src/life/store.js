import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Nirvaah "life" data layer — notes, tasks and life events.
 * Everything lives in localStorage so the app stays usable offline, with a
 * shared change event so every mounted page (and the sidebar badges) stay in
 * sync — including across tabs.
 */

export const NOTES_KEY = 'moneta_notes';
export const TASKS_KEY = 'moneta_tasks';
export const EVENTS_KEY = 'moneta_events';
export const ACTIVITY_KEY = 'moneta_activity';

const CHANGE_EVENT = 'moneta:data-change';

export const uid = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;

/* ── Categories ─────────────────────────────────────────────────────────── */

export const TINTS = {
    Money: '#d97757', Bills: '#d97757', Life: '#d97757',
    Tax: '#c9a227', Milestone: '#c9a227',
    Goals: '#7fa650', Planning: '#7fa650', Savings: '#7fa650',
    Ideas: '#a78bd0', Health: '#5f9ea0',
    Work: '#6a9bd0', Travel: '#6fa8a0',
    Home: '#b08d6a', Family: '#d98fb0', Personal: '#a89f94',
};

export const NOTE_CATEGORIES = ['Money', 'Tax', 'Goals', 'Ideas', 'Health', 'Work', 'Personal'];
export const TASK_CATEGORIES = ['Bills', 'Tax', 'Planning', 'Savings', 'Health', 'Home', 'Personal'];
export const EVENT_CATEGORIES = ['Life', 'Money', 'Health', 'Work', 'Family', 'Travel', 'Home', 'Milestone'];

export const PRIORITIES = [
    { id: 'high', label: 'High', tint: '#d97757', rank: 0 },
    { id: 'medium', label: 'Medium', tint: '#c9a227', rank: 1 },
    { id: 'low', label: 'Low', tint: '#7fa650', rank: 2 },
];
export const priorityMeta = id => PRIORITIES.find(p => p.id === id) || PRIORITIES[1];
// Categories the user invents still need a colour. Known names keep their
// curated tint; anything else is hashed onto a 15-anchor hue wheel, so a new
// tab is coloured the moment it is created — no registration step.
const TINT_HUES = [10, 24, 38, 50, 70, 96, 148, 170, 192, 212, 238, 262, 288, 320, 344];

export const tintOf = name => {
    if (TINTS[name]) return TINTS[name];
    const value = String(name || '').toLowerCase().trim();
    if (!value) return '#a89f94';
    let h = 0;
    for (let i = 0; i < value.length; i++) h = (h * 33 + value.charCodeAt(i)) >>> 0;
    return `hsl(${TINT_HUES[h % TINT_HUES.length]} 42% 50%)`;
};

/* ── Editable category (tab) lists ──────────────────────────────────────────
   Notes / Tasks / Journal each own a list of categories. They start from the
   defaults above but are user-managed: add, rename, reorder-by-delete, all
   persisted to localStorage and shared across mounted pages. */

const CATEGORY_KEYS = {
    note: 'moneta_note_categories',
    task: 'moneta_task_categories',
    event: 'moneta_event_categories',
};

const CATEGORY_DEFAULTS = {
    note: NOTE_CATEGORIES,
    task: TASK_CATEGORIES,
    event: EVENT_CATEGORIES,
};

const CATEGORY_EVENT = 'moneta:categories-change';
const categoryListeners = new Set();

export function readCategories(kind) {
    try {
        const raw = localStorage.getItem(CATEGORY_KEYS[kind]);
        if (raw) {
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed) && parsed.length) return parsed.filter(c => typeof c === 'string' && c.trim());
        }
    } catch { /* ignore */ }
    return CATEGORY_DEFAULTS[kind];
}

export function writeCategories(kind, list) {
    const next = list.map(c => String(c).trim()).filter(Boolean);
    if (!next.length) return readCategories(kind);
    try { localStorage.setItem(CATEGORY_KEYS[kind], JSON.stringify(next)); } catch { /* ignore */ }
    categoryListeners.forEach(fn => fn(kind, next));
    return next;
}

export function useCategories(kind) {
    const [list, setList] = useState(() => readCategories(kind));
    useEffect(() => {
        const fn = (k, next) => { if (k === kind) setList(next); };
        categoryListeners.add(fn);
        const onStorage = e => { if (e.key === CATEGORY_KEYS[kind]) setList(readCategories(kind)); };
        window.addEventListener('storage', onStorage);
        setList(readCategories(kind));
        return () => { categoryListeners.delete(fn); window.removeEventListener('storage', onStorage); };
    }, [kind]);
    const update = useCallback(next => setList(writeCategories(kind, next)), [kind]);
    return [list, update];
}

/* ── Dates ──────────────────────────────────────────────────────────────── */

export const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export const todayISO = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export const shiftISO = (iso, days) => {
    const d = iso ? new Date(`${iso}T00:00:00`) : new Date();
    d.setDate(d.getDate() + days);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export function parseDate(value) {
    if (!value) return null;
    if (typeof value === 'number') return value;
    const iso = String(value).slice(0, 10);
    if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
        const t = new Date(`${iso}T00:00:00`).getTime();
        return Number.isNaN(t) ? null : t;
    }
    const t = new Date(value).getTime();
    return Number.isNaN(t) ? null : t;
}

export const toISODate = value => {
    const t = parseDate(value);
    if (!t) return '';
    const d = new Date(t);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export const formatDay = value => {
    const t = parseDate(value);
    if (!t) return 'No date';
    const d = new Date(t);
    return `${String(d.getDate()).padStart(2, '0')} ${MONTHS_SHORT[d.getMonth()]} ${d.getFullYear()}`;
};

export const shortDay = value => {
    const t = parseDate(value);
    if (!t) return 'No date';
    const d = new Date(t);
    return `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`;
};

export const monthKey = value => {
    const t = parseDate(value);
    if (!t) return 'No date';
    const d = new Date(t);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
};

export const monthLabel = key => {
    if (!key || key === 'No date') return 'No date';
    const [y, m] = key.split('-');
    return `${MONTHS_SHORT[Number(m) - 1]} ${y}`;
};

export function timeAgo(value) {
    const t = parseDate(value);
    if (!t) return '';
    const diff = Date.now() - t;
    const min = Math.floor(diff / 60000);
    if (min < 1) return 'just now';
    if (min < 60) return `${min}m ago`;
    const hrs = Math.floor(min / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    if (days < 7) return `${days}d ago`;
    if (days < 30) return `${Math.floor(days / 7)}w ago`;
    return formatDay(t);
}

export const isOverdue = iso => !!iso && iso < todayISO();

export const wordCount = text => (String(text || '').trim().match(/\S+/g) || []).length;

/* ── Storage primitives ─────────────────────────────────────────────────── */

function readJSON(key, fallback) {
    try {
        const raw = localStorage.getItem(key);
        if (!raw) return fallback;
        const parsed = JSON.parse(raw);
        return parsed ?? fallback;
    } catch {
        return fallback;
    }
}

function writeJSON(key, value) {
    try {
        localStorage.setItem(key, JSON.stringify(value));
    } catch { /* storage full / private mode */ }
    window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: key }));
}

/* ── Normalisation (keeps existing saved data working) ──────────────────── */

// A record's category is data, not a preference. The managed list is per
// browser; validating against it would silently rewrite categories that were
// created on another device (and then push the rewrite to the server).
const keepCategory = (value, fallback) => {
    const text = typeof value === 'string' ? value.trim() : '';
    return text || fallback;
};

export const normalizeNote = n => ({
    id: n.id ?? uid(),
    title: (n.title || '').trim() || 'Untitled note',
    body: n.body ?? n.content ?? '',
    category: keepCategory(n.category, 'Personal'),
    tags: Array.isArray(n.tags) ? n.tags.filter(Boolean) : [],
    pinned: !!n.pinned,
    archived: !!n.archived,
    createdAt: n.createdAt || parseDate(n.date) || Date.now(),
    updatedAt: n.updatedAt || parseDate(n.date) || Date.now(),
});

export const normalizeTask = t => {
    const rawTag = t.category || t.tag;
    return {
        id: t.id ?? uid(),
        text: (t.text || '').trim() || 'Untitled task',
        notes: t.notes || '',
        done: !!t.done,
        priority: ['high', 'medium', 'low'].includes(t.priority)
            ? t.priority
            : (t.tag === 'High' ? 'high' : t.priorityRank === 0 ? 'high' : 'medium'),
        category: keepCategory(rawTag, 'Personal'),
        due: toISODate(t.due),
        amount: t.amount ? Number(t.amount) : '',
        createdAt: t.createdAt || Date.now(),
        completedAt: t.completedAt || (t.done ? Date.now() : null),
    };
};

export const normalizeEvent = e => ({
    id: e.id ?? uid(),
    title: (e.title || '').trim() || 'Untitled event',
    description: e.description || '',
    category: keepCategory(e.category, 'Life'),
    mood: e.mood || 'steady',
    amount: e.amount === '' || e.amount == null ? '' : Number(e.amount),
    tags: Array.isArray(e.tags) ? e.tags.filter(Boolean) : [],
    date: toISODate(e.date) || todayISO(),
    createdAt: e.createdAt || Date.now(),
});

const DEFAULTS = {
    [NOTES_KEY]: [],
    [TASKS_KEY]: [],
    [EVENTS_KEY]: [],
};

const NORMALIZERS = {
    [NOTES_KEY]: items => items.map(normalizeNote),
    [TASKS_KEY]: items => items.map(normalizeTask),
    [EVENTS_KEY]: items => items.map(normalizeEvent),
};

export function loadCollection(key) {
    const raw = readJSON(key, DEFAULTS[key] || []);
    const list = Array.isArray(raw) ? raw : [];
    const normalized = NORMALIZERS[key] ? NORMALIZERS[key](list) : list;
    // Write the migrated shape back once so old records keep their new fields.
    if (JSON.stringify(normalized) !== JSON.stringify(list)) {
        try { localStorage.setItem(key, JSON.stringify(normalized)); } catch { }
    }
    return normalized;
}

// Chips and pickers show the managed categories plus every category a record
// actually uses, so a category created on another device stays selectable.
export const categoryPool = (managed, records) => {
    const seen = new Set((managed || []).filter(Boolean));
    (records || []).forEach(r => { if (r && r.category) seen.add(r.category); });
    return [...seen];
};

/* ── Activity log ───────────────────────────────────────────────────────── */

const SEED_ACTIVITY = [
    { id: uid(), action: 'Workspace opened', detail: 'Your Nirvaah space is ready.', type: 'system', at: Date.now() - 1000 * 60 * 4 },
    { id: uid(), action: 'Notes synced locally', detail: 'Everything is stored on this device.', type: 'note', at: Date.now() - 1000 * 60 * 26 },
];

export function loadActivity() {
    const raw = readJSON(ACTIVITY_KEY, null);
    if (Array.isArray(raw) && raw.length) return raw;
    return SEED_ACTIVITY;
}

export function logActivity(action, type = 'system', detail = '') {
    if (!action) return;
    const entry = { id: uid(), action, detail, type, at: Date.now() };
    const next = [entry, ...loadActivity()].slice(0, 400);
    writeJSON(ACTIVITY_KEY, next);
    return entry;
}

/* ── Server sync for life records ─────────────────────────────────────────
   localStorage stays the instant-paint cache; Postgres is the source of
   truth. Records carry a client-generated id, so an offline create is the
   same row the server will hold, and a diff is all that has to travel. */

const API = (import.meta.env && import.meta.env.VITE_API_URL) || 'http://localhost:8001/api';

const ENDPOINTS = {
    [NOTES_KEY]: 'notes',
    [TASKS_KEY]: 'tasks',
    [EVENTS_KEY]: 'journal',
};

const authHeaders = () => {
    const token = (typeof localStorage !== 'undefined' && localStorage.getItem('moneta_token')) || '';
    return {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
};

const payloadOf = record => {
    const { updatedAt, ...rest } = record || {};
    return rest;
};

export function writeCollection(key, list) {
    try { localStorage.setItem(key, JSON.stringify(list)); } catch { }
}

async function fetchCollection(key) {
    const endpoint = ENDPOINTS[key];
    if (!endpoint || typeof fetch === 'undefined') return null;
    try {
        const res = await fetch(`${API}/${endpoint}`, { headers: authHeaders() });
        if (!res.ok) return null;
        const rows = await res.json();
        return Array.isArray(rows) ? rows : null;
    } catch {
        return null;
    }
}

async function fetchDeletions(key) {
    const endpoint = ENDPOINTS[key];
    if (!endpoint || typeof fetch === 'undefined') return new Set();
    try {
        const res = await fetch(`${API}/deletions?kind=${endpoint}`, { headers: authHeaders() });
        if (!res.ok) return new Set();
        const rows = await res.json();
        return new Set((Array.isArray(rows) ? rows : []).map(r => r.id));
    } catch {
        return new Set();
    }
}

async function pushCollection(key, endpoint, body, method) {
    try {
        const res = await fetch(`${API}/${endpoint}${method === 'DELETE' ? `/${body.id}` : ''}`, {
            method,
            headers: authHeaders(),
            ...(method === 'DELETE' ? {} : { body: JSON.stringify(body) }),
        });
        return res.ok;
    } catch {
        return false;
    }
}

// Diff two versions of a list and send only what changed.
export function syncCollection(key, previous, next) {
    const endpoint = ENDPOINTS[key];
    if (!endpoint) return Promise.resolve();
    const before = new Map((previous || []).map(r => [r.id, JSON.stringify(r)]));
    const after = new Map((next || []).map(r => [r.id, r]));

    const jobs = [];
    after.forEach((record, id) => {
        const serialized = JSON.stringify(record);
        if (!before.has(id) || before.get(id) !== serialized) {
            jobs.push(pushCollection(key, endpoint, payloadOf(record), 'POST'));
        }
    });
    before.forEach((_value, id) => {
        if (!after.has(id)) jobs.push(pushCollection(key, endpoint, { id }, 'DELETE'));
    });
    return Promise.all(jobs);
}

// Merge on first load, never replace. Records that exist only in this browser
// (created before the server existed, or on another origin that has since been
// opened) are pushed up; records that exist only on the server come down; when
// both sides hold the same id the newer write wins. Nothing is dropped.
const stampOf = record => {
    const value = record && (record.updatedAt ?? record.createdAt);
    if (typeof value === 'number') return value;
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : 0;
};

export function hydrateCollection(key, local, apply) {
    if (!ENDPOINTS[key]) return () => { };
    let alive = true;
    Promise.all([fetchCollection(key), fetchDeletions(key)]).then(([rows, deleted]) => {
        if (!alive || !rows) return;
        const alive_ = row => !deleted.has(row.id);
        const serverList = (NORMALIZERS[key] ? NORMALIZERS[key](rows) : rows).filter(alive_);
        const localList = (Array.isArray(local) ? local : []).filter(alive_);

        const byId = new Map(serverList.map(r => [r.id, r]));
        const onlyLocal = [];
        localList.forEach(record => {
            const server = byId.get(record.id);
            if (!server) {
                onlyLocal.push(record);
                byId.set(record.id, record);
                return;
            }
            if (stampOf(record) > stampOf(server)) {
                onlyLocal.push(record);
                byId.set(record.id, record);
            }
        });

        const merged = [...byId.values()];
        if (onlyLocal.length) syncCollection(key, [], onlyLocal);
        // Also rewrite when the merge only *removed* something (a tombstoned
        // record from another device); otherwise the stale cache stays on screen.
        const dropped = (Array.isArray(local) ? local.length : 0) !== localList.length;
        if (merged.length || localList.length || dropped) {
            writeCollection(key, merged);
            apply(merged);
        }
    });
    return () => { alive = false; };
}

/* ── React bindings ─────────────────────────────────────────────────────── */

/* ── Cross-device freshness ──────────────────────────────────────────────
   A tiny poll is enough to make two devices feel live: the server exposes a
   fingerprint of this user's records, and a change in it triggers one
   re-hydrate per mounted collection. No socket, no broker, no extra process. */

export const REMOTE_CHANGE = 'moneta:remote-change';

let lastVersion = null;
let pollTimer = null;

async function pollVersion() {
    try {
        const res = await fetch(`${API}/sync/version`, { headers: authHeaders() });
        if (!res.ok) return;
        const { version } = await res.json();
        if (!version) return;
        if (lastVersion === null) {
            lastVersion = version;
            return;
        }
        if (version !== lastVersion) {
            lastVersion = version;
            window.dispatchEvent(new Event(REMOTE_CHANGE));
        }
    } catch { /* offline — the next tick tries again */ }
}

export function startSyncWatch(intervalMs = 7000) {
    if (pollTimer) return;
    pollVersion();
    pollTimer = setInterval(pollVersion, intervalMs);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) pollVersion();
    });
}

export function stopSyncWatch() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    lastVersion = null;
}

export function useCollection(key) {
    const [items, setItems] = useState(() => loadCollection(key));
    const latest = useRef(items);
    latest.current = items;

    const pull = useCallback(() => {
        hydrateCollection(key, latest.current, rows => {
            latest.current = rows;
            setItems(rows);
        });
    }, [key]);

    useEffect(() => {
        // Another device wrote something: pull the merged copy again.
        const remote = () => pull();
        const sync = event => {
            if (event && event.detail && event.detail !== key) return;
            const next = loadCollection(key);
            latest.current = next;
            setItems(next);
        };
        window.addEventListener(CHANGE_EVENT, sync);
        window.addEventListener('storage', sync);
        window.addEventListener(REMOTE_CHANGE, remote);
        pull();
        return () => {
            window.removeEventListener(CHANGE_EVENT, sync);
            window.removeEventListener('storage', sync);
            window.removeEventListener(REMOTE_CHANGE, remote);
        };
    }, [key, pull]);

    const commit = useCallback(next => {
        const previous = latest.current;
        const value = typeof next === 'function' ? next(previous) : next;
        latest.current = value;
        writeJSON(key, value);
        setItems(value);
        syncCollection(key, previous, value);
        return value;
    }, [key]);

    return [items, commit];
}

export function useActivity() {
    const [entries, setEntries] = useState(() => loadActivity());
    useEffect(() => {
        const sync = event => {
            if (event && event.detail && event.detail !== ACTIVITY_KEY) return;
            setEntries(loadActivity());
        };
        window.addEventListener(CHANGE_EVENT, sync);
        window.addEventListener('storage', sync);
        return () => {
            window.removeEventListener(CHANGE_EVENT, sync);
            window.removeEventListener('storage', sync);
        };
    }, []);
    return entries;
}

export const clearActivity = () => writeJSON(ACTIVITY_KEY, []);

/* ── Small display helpers shared by the pages ──────────────────────────── */

export const moodMeta = mood => ({
    great: { label: 'Great', glyph: '☀', tint: '#c9a227' },
    good: { label: 'Good', glyph: '◔', tint: '#7fa650' },
    steady: { label: 'Steady', glyph: '◍', tint: '#6a9bd0' },
    low: { label: 'Low', glyph: '◕', tint: '#a78bd0' },
    hard: { label: 'Hard', glyph: '☂', tint: '#d97757' },
}[mood] || { label: 'Steady', glyph: '◍', tint: '#6a9bd0' });
