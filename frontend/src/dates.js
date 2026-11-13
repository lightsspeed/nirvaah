/**
 * Two kinds of value, deliberately never mixed.
 *
 * Timestamps — an exact instant. The API sends UTC with an explicit `Z`, and we
 *   display it in the browser's own timezone.
 * Date-only — a calendar day ("2026-12-01") with no timezone at all. It must read
 *   as the same day everywhere, so it is parsed from its own components and never
 *   round-tripped through UTC.
 *
 * `new Date('2026-12-01')` is UTC midnight — the trap this module exists to avoid.
 */

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
// "2026-11-13T04:21:52" / "2026-11-13T04:21:52.870807" — an instant with no offset.
const NAIVE_ISO = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;
const pad = n => String(n).padStart(2, '0');

/** True for a bare calendar day, false for a timestamp string. */
export const isDateOnly = value =>
    typeof value === 'string' && !value.includes('T') && DATE_ONLY.test(value.trim().slice(0, 10));

/** Calendar day → local-midnight Date (or null). Never shifts across timezones. */
export const parseDateOnly = value => {
    if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
    if (typeof value !== 'string') return null;
    const text = value.trim();
    // A timestamp is an instant, not a day — refuse it rather than truncating the
    // time off and pretending the UTC date was the user's date.
    if (text.includes('T')) return null;
    const day = text.slice(0, 10);
    if (!DATE_ONLY.test(day)) return null;
    const d = new Date(`${day}T00:00:00`);
    return Number.isNaN(d.getTime()) ? null : d;
};

/** Timestamp → Date in the browser's timezone (or null). Needs an explicit offset. */
export const parseInstant = value => {
    if (value === null || value === undefined || value === '') return null;
    if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
    if (typeof value === 'number') {
        const fromNumber = new Date(value);
        return Number.isNaN(fromNumber.getTime()) ? null : fromNumber;
    }
    let text = String(value).trim();
    // The API's contract is UTC. A string with no `Z` and no `±hh:mm` must be read
    // as UTC, never as browser-local — otherwise a bare "2026-11-13T04:21:52" is
    // silently shifted by the local offset.
    if (NAIVE_ISO.test(text)) text += 'Z';
    const d = new Date(text);
    return Number.isNaN(d.getTime()) ? null : d;
};

/** Calendar day as "YYYY-MM-DD" from local components. */
export const dayKey = value => {
    const d = parseDateOnly(value);
    return d ? `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` : '';
};

export const yearOf = value => {
    const d = parseDateOnly(value);
    return d ? d.getFullYear() : null;
};

export const formatDateOnly = (value, options) => {
    const d = parseDateOnly(value);
    return d ? d.toLocaleDateString('en-IN', options) : '';
};

export const formatInstant = (value, options) => {
    const d = parseInstant(value);
    return d ? d.toLocaleDateString('en-IN', options) : '';
};
