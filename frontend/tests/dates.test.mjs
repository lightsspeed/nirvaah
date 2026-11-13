/**
 * Date-only vs timestamp, with no build step and no new dependency.
 *
 * Run with the process timezone set (the suite is executed for UTC, Asia/Kolkata
 * and America/Los_Angeles); every expectation is computed from process.env.TZ, so
 * the same file proves the right behaviour in each zone instead of assuming one.
 *
 *   TZ=Asia/Kolkata node --test tests/
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
    parseDateOnly, parseInstant, dayKey, yearOf, formatDateOnly, formatInstant, isDateOnly,
} from '../src/dates.js';

// The zone the runtime actually resolved (process.env.TZ on Windows/git-bash does
// not always survive, so trust Intl rather than the environment variable).
const RESOLVED = Intl.DateTimeFormat().resolvedOptions().timeZone;
const TZ = RESOLVED === 'Asia/Calcutta' ? 'Asia/Kolkata' : RESOLVED;
const SHORT = { day: '2-digit', month: 'short' };

const localLabel = (iso, tz = TZ) =>
    new Intl.DateTimeFormat('en-IN', { ...SHORT, timeZone: tz }).format(new Date(iso));

// ── date-only: a calendar day, identical in every timezone ──────────────────

test('date-only parses to local midnight of the same calendar day', () => {
    const d = parseDateOnly('2026-12-01');
    assert.equal(d.getFullYear(), 2026);
    assert.equal(d.getMonth(), 11);
    assert.equal(d.getDate(), 1);
    assert.equal(d.getHours(), 0);
    assert.equal(dayKey('2026-12-01'), '2026-12-01');
    assert.equal(yearOf('2026-12-01'), 2026);
});

test('a date-only value never shifts: the same day in India, UTC and Los Angeles', () => {
    // parseDateOnly reads the components itself, so the day is the same everywhere.
    const d = parseDateOnly('2026-12-01');
    assert.deepEqual([d.getFullYear(), d.getMonth(), d.getDate()], [2026, 11, 1]);
    assert.equal(dayKey('2026-12-01'), '2026-12-01');
    assert.equal(formatDateOnly('2026-12-01', SHORT), '01 Dec');

    // Contrast: the naive parse is an instant, so its local day differs by zone —
    // that is the bug this helper exists to avoid.
    const utcMidnight = new Date('2026-12-01');
    const dayIn = tz => new Intl.DateTimeFormat('en-GB', { day: '2-digit', timeZone: tz }).format(utcMidnight);
    assert.equal(dayIn('Asia/Kolkata'), '01');
    assert.equal(dayIn('UTC'), '01');
    assert.equal(dayIn('America/Los_Angeles'), '30');
});

test('the naive-parse trap is avoided', () => {
    // new Date('2026-12-01') is UTC midnight, which is 30 Nov in Los Angeles.
    const naive = new Date('2026-12-01');
    assert.equal(parseDateOnly('2026-12-01').getDate(), 1);
    if (TZ === 'America/Los_Angeles') assert.equal(naive.getDate(), 30);
});

test('date-only rejects timestamps and junk', () => {
    assert.equal(isDateOnly('2026-12-01'), true);
    assert.equal(isDateOnly('2026-12-01T00:00:00Z'), false);
    assert.equal(parseDateOnly('2026-12-01T00:00:00Z'), null);
    assert.equal(parseDateOnly('not a date'), null);
    assert.equal(parseDateOnly(null), null);
    assert.equal(parseDateOnly(undefined), null);
    assert.equal(dayKey('nope'), '');
    assert.equal(yearOf(null), null);
    assert.equal(formatDateOnly(null, SHORT), '');
});

// ── timestamps: an instant, rendered in the process timezone ────────────────

test('a UTC timestamp keeps its instant', () => {
    const iso = '2026-11-12T20:00:00Z';
    assert.equal(parseInstant(iso).getTime(), Date.UTC(2026, 10, 12, 20, 0, 0));
    assert.equal(formatInstant(iso, SHORT), localLabel(iso));
});

test('the same instant lands on different calendar days by zone', () => {
    const iso = '2026-11-12T20:00:00Z';          // 01:30 IST on the 13th, 12:00 PST on the 12th
    const expected = {
        'Asia/Kolkata': '13 Nov',
        UTC: '12 Nov',
        'America/Los_Angeles': '12 Nov',
    }[TZ];
    assert.equal(formatInstant(iso, SHORT), expected);
});

test('a timestamp with an offset is normalized by the browser', () => {
    const iso = '2026-11-13T01:30:00+05:30';      // the same instant as 20:00Z on the 12th
    assert.equal(parseInstant(iso).getTime(), Date.UTC(2026, 10, 12, 20, 0, 0));
});

test('a timestamp with no offset is read as UTC, never as browser-local', () => {
    // the API's contract, and the shape an older server sends
    const cases = [
        ['2026-11-13T04:21:52', Date.UTC(2026, 10, 13, 4, 21, 52)],
        ['2026-11-13T04:21:52.870807', Date.UTC(2026, 10, 13, 4, 21, 52, 870)],   // JS keeps ms
    ];
    for (const [naive, expected] of cases) {
        assert.equal(parseInstant(naive).getTime(), expected, `${naive} must be UTC in ${TZ}`);
    }
});

test('timestamps handle null and invalid input safely', () => {
    assert.equal(parseInstant(null), null);
    assert.equal(parseInstant(undefined), null);
    assert.equal(parseInstant(''), null);
    assert.equal(parseInstant('definitely not a date'), null);
    assert.equal(formatInstant('definitely not a date', SHORT), '');
});

test('journal and transaction days do not shift through the helper', () => {
    // the two values that used to go through new Date(value) directly
    assert.equal(formatDateOnly('2026-11-11', SHORT), '11 Nov');   // journal event_date
    assert.equal(formatDateOnly('2026-11-12', SHORT), '12 Nov');   // transaction txn_date
});
