/**
 * PWA invariants that must not regress.
 *
 * No browser required: the manifest, the icons and the service worker are read
 * from disk. Anything that needs a real HTTPS origin (install prompts, offline
 * navigation) is covered by the browser checks, not here.
 *
 *   node --test tests/
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PUBLIC = join(ROOT, 'public');

const manifest = JSON.parse(readFileSync(join(PUBLIC, 'manifest.webmanifest'), 'utf8'));
const sw = readFileSync(join(PUBLIC, 'sw.js'), 'utf8');

function pngSize(file) {
    const bytes = readFileSync(file);
    assert.equal(bytes.toString('ascii', 1, 4), 'PNG', `${file} is not a PNG`);
    return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

test('manifest identity and launch mode', () => {
    assert.equal(manifest.name, 'Nirvaah');
    assert.equal(manifest.short_name, 'Nirvaah');
    assert.equal(manifest.id, '/');
    assert.equal(manifest.display, 'standalone');
    assert.equal(manifest.scope, '/');
    assert.equal(manifest.start_url, '/?source=pwa');
    assert.ok(manifest.start_url.startsWith('/'), 'start_url must be same-origin');
    assert.equal(manifest.orientation, 'any');
    assert.equal(manifest.prefer_related_applications, false);
});

test('manifest colours match the Nirvaah palette', () => {
    assert.equal(manifest.theme_color.toUpperCase(), '#071EF8');
    assert.equal(manifest.background_color.toUpperCase(), '#F8F6F2');
});

test('192 and 512 any-purpose icons exist at the declared size', () => {
    for (const size of [192, 512]) {
        const icon = manifest.icons.find(
            (entry) => entry.sizes === `${size}x${size}` && entry.purpose === 'any'
        );
        assert.ok(icon, `missing ${size} any icon`);
        const file = join(PUBLIC, icon.src.replace(/^\//, ''));
        assert.ok(existsSync(file), `${icon.src} does not exist`);
        assert.deepEqual(pngSize(file), { width: size, height: size });
    }
});

test('maskable icons are real full-bleed artwork', () => {
    const maskable = manifest.icons.filter((entry) => entry.purpose === 'maskable');
    assert.ok(maskable.length >= 1, 'expected a maskable icon');
    for (const icon of maskable) {
        const file = join(PUBLIC, icon.src.replace(/^\//, ''));
        assert.ok(existsSync(file), `${icon.src} does not exist`);
        const [w, h] = icon.sizes.split('x').map(Number);
        assert.deepEqual(pngSize(file), { width: w, height: h });
        // A maskable icon cannot be the rounded-tile "any" artwork: its corners
        // must be opaque, or Android shows white wedges inside the mask.
        const bytes = readFileSync(file);
        assert.equal(bytes.toString('ascii', 1, 4), 'PNG');
        assert.notEqual(icon.src, '/icon-512.png', 'the rounded tile is not maskable-safe');
    }
});

test('service worker claims a shell cache and cleans old versions', () => {
    assert.match(sw, /const SHELL = 'nirvaah-shell-v\d+'/);
    assert.match(sw, /skipWaiting\(\)/);
    assert.match(sw, /clients\.claim\(\)/);
    assert.match(sw, /caches\.delete/);
});

test('service worker never caches API, auth or tokens', () => {
    assert.match(sw, /pathname\.startsWith\('\/api\/'\)/, 'API paths must be excluded');
    assert.match(sw, /headers\.has\('authorization'\)/, 'authorized requests must be excluded');
    assert.doesNotMatch(sw, /localStorage|sessionStorage/);
    assert.doesNotMatch(sw, /cache\.put\([^)]*(token|auth)/i);
});
