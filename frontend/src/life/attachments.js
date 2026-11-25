import { apiUrl, authHeaders } from './store';

/**
 * Images and files attached to a note or a task.
 *
 * The API owns the bytes (and the metadata): this module only compresses large
 * photos before upload, and fetches a blob back when a preview or a download is
 * needed. Attachment ids are stable across devices, so the same record renders
 * on a laptop and a phone from the metadata stored with it.
 */

export const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;
export const MAX_ATTACHMENTS_PER_RECORD = 12;
export const MAX_ATTACHMENTS_TOTAL_BYTES = 24 * 1024 * 1024;

// Photos straight off a phone are routinely 3–8 MB. Shrinking them before the
// upload keeps the request well under the proxy's body limit and the database
// row a sane size, without asking the user to resize anything by hand.
const IMAGE_EDGE = 2048;
const IMAGE_SOFT_BYTES = 1.6 * 1024 * 1024;
const IMAGE_QUALITY = 0.84;

export const isImageAttachment = (attachment) =>
    Boolean(attachment) && /^image\/(jpeg|png|webp|gif)$/.test(String(attachment.mime || ''));

export function formatBytes(bytes) {
    const value = Number(bytes) || 0;
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
    return `${(value / (1024 * 1024)).toFixed(value < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

async function compressImage(file) {
    if (!String(file.type || '').startsWith('image/') || file.type === 'image/gif') return file;
    if (file.size <= IMAGE_SOFT_BYTES) return file;
    if (typeof document === 'undefined' || typeof createImageBitmap !== 'function') return file;

    try {
        const bitmap = await createImageBitmap(file);
        const scale = Math.min(1, IMAGE_EDGE / Math.max(bitmap.width, bitmap.height));
        const width = Math.max(1, Math.round(bitmap.width * scale));
        const height = Math.max(1, Math.round(bitmap.height * scale));
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext('2d');
        if (!context) {
            bitmap.close?.();
            return file;
        }
        // JPEG has no alpha channel; paint white first so a transparent PNG
        // does not come back with a black background.
        context.fillStyle = '#ffffff';
        context.fillRect(0, 0, width, height);
        context.drawImage(bitmap, 0, 0, width, height);
        bitmap.close?.();
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', IMAGE_QUALITY));
        if (!blob || blob.size >= file.size) return file;
        const base = String(file.name || 'image').replace(/\.[^.]+$/, '') || 'image';
        return new File([blob], `${base}.jpg`, { type: 'image/jpeg' });
    } catch {
        // An unsupported codec (or a broken bitmap) is not a reason to block the
        // upload: send the original and let the size check decide.
        return file;
    }
}

async function readError(res) {
    try {
        const body = await res.json();
        if (body && typeof body.detail === 'string') return body.detail;
        if (body && typeof body.error === 'string') return body.error;
    } catch {
        /* not JSON */
    }
    return `Upload failed (HTTP ${res.status})`;
}

export async function uploadAttachment(file, kind, ownerId) {
    const prepared = await compressImage(file);
    if (prepared.size > MAX_ATTACHMENT_BYTES) {
        throw new Error(`"${file.name}" is larger than ${formatBytes(MAX_ATTACHMENT_BYTES)}.`);
    }
    const body = new FormData();
    body.append('file', prepared, prepared.name || 'attachment');
    body.append('owner_kind', kind);
    body.append('owner_id', ownerId);
    const res = await fetch(apiUrl('/attachments'), {
        method: 'POST',
        headers: authHeaders({ json: false }),
        body,
    });
    if (!res.ok) throw new Error(await readError(res));
    return res.json();
}

export async function deleteAttachment(id) {
    const res = await fetch(apiUrl(`/attachments/${encodeURIComponent(id)}`), {
        method: 'DELETE',
        headers: authHeaders({ json: false }),
    });
    if (!res.ok && res.status !== 404) throw new Error(await readError(res));
}

/** Fetch the bytes and hand back an object URL. The caller revokes it. */
export async function fetchAttachmentUrl(id) {
    const res = await fetch(apiUrl(`/attachments/${encodeURIComponent(id)}`), {
        headers: authHeaders({ json: false }),
    });
    if (!res.ok) throw new Error(await readError(res));
    return URL.createObjectURL(await res.blob());
}
