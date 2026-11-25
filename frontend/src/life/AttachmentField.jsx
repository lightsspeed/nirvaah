import React, { useEffect, useRef, useState } from 'react';
import { FileText, Loader2, Paperclip, X } from 'lucide-react';
import {
    MAX_ATTACHMENTS_PER_RECORD,
    MAX_ATTACHMENTS_TOTAL_BYTES,
    deleteAttachment,
    fetchAttachmentUrl,
    formatBytes,
    isImageAttachment,
    uploadAttachment,
} from './attachments';

function AttachmentThumb({ attachment }) {
    const [url, setUrl] = useState('');
    const wantsImage = isImageAttachment(attachment);

    useEffect(() => {
        if (!wantsImage) return undefined;
        let alive = true;
        let objectUrl = '';
        fetchAttachmentUrl(attachment.id)
            .then((next) => {
                if (!alive) {
                    URL.revokeObjectURL(next);
                    return;
                }
                objectUrl = next;
                setUrl(next);
            })
            .catch(() => {
                /* the row still shows the file name */
            });
        return () => {
            alive = false;
            if (objectUrl) URL.revokeObjectURL(objectUrl);
        };
    }, [attachment.id, wantsImage]);

    if (wantsImage && url) {
        return <img className="attachment-thumb" src={url} alt="" loading="lazy" />;
    }
    return (
        <span className="attachment-thumb is-file">
            <FileText size={14} strokeWidth={1.8} />
        </span>
    );
}

function AttachmentItem({ attachment, onRemove }) {
    const [busy, setBusy] = useState(false);

    const download = async () => {
        if (busy) return;
        setBusy(true);
        try {
            const objectUrl = await fetchAttachmentUrl(attachment.id);
            const link = document.createElement('a');
            link.href = objectUrl;
            link.download = attachment.name || 'attachment';
            link.rel = 'noopener';
            document.body.appendChild(link);
            link.click();
            link.remove();
            // Give the browser time to start the download before revoking.
            window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
        } catch {
            /* a failed download leaves the metadata untouched */
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="attachment-item">
            <AttachmentThumb attachment={attachment} />
            <button type="button" className="attachment-name" onClick={download} title={`Download ${attachment.name}`}>
                <span>{attachment.name}</span>
                <small>{formatBytes(attachment.size)}</small>
            </button>
            <button
                type="button"
                className="life-icon-btn is-danger attachment-remove"
                onClick={() => onRemove(attachment)}
                title={`Remove ${attachment.name}`}
                aria-label={`Remove ${attachment.name}`}
                disabled={busy}
            >
                {busy ? <Loader2 size={13} className="spin" /> : <X size={13} />}
            </button>
        </div>
    );
}

/**
 * Attach images or files to a note or a task.
 *
 * The record id is generated on the client before it is saved, so a brand-new
 * note or task can take attachments before its row exists. Removing an item
 * deletes the stored blob as well; an abandoned draft is cleaned up by the
 * page that owns it.
 */
export default function AttachmentField({
    kind,
    ownerId,
    value = [],
    onChange,
    label = 'Attachments',
    hint = 'images or files',
    disabled = false,
}) {
    const [uploading, setUploading] = useState(false);
    const [error, setError] = useState('');
    const inputRef = useRef(null);
    const attachments = Array.isArray(value) ? value : [];

    const pickFiles = async (event) => {
        const picked = Array.from(event.target.files || []);
        event.target.value = '';
        if (!picked.length) return;
        const room = MAX_ATTACHMENTS_PER_RECORD - attachments.length;
        if (room <= 0) {
            setError(`A record can hold ${MAX_ATTACHMENTS_PER_RECORD} attachments.`);
            return;
        }
        setError('');
        setUploading(true);
        let next = [...attachments];
        let total = attachments.reduce((sum, a) => sum + (Number(a.size) || 0), 0);
        for (const file of picked.slice(0, room)) {
            // Images are compressed before upload, so only a document's real
            // size can be judged here; the API enforces the cap for both.
            const compressible = /^image\//.test(file.type) && file.type !== 'image/gif';
            if (!compressible && total + file.size > MAX_ATTACHMENTS_TOTAL_BYTES) {
                setError(
                    `This record's attachments are limited to ${formatBytes(MAX_ATTACHMENTS_TOTAL_BYTES)} in total.`
                );
                break;
            }
            try {
                const meta = await uploadAttachment(file, kind, ownerId);
                next = [...next, meta];
                total += Number(meta.size) || 0;
                onChange(next);
            } catch (err) {
                setError(err instanceof Error ? err.message : `Could not attach "${file.name}".`);
            }
        }
        if (picked.length > room) {
            setError(`Only ${room} more attachment${room === 1 ? '' : 's'} fit on this record.`);
        }
        setUploading(false);
    };

    const remove = async (attachment) => {
        onChange(attachments.filter((a) => a.id !== attachment.id));
        try {
            await deleteAttachment(attachment.id);
        } catch {
            // The record no longer references it; a blob left behind is better
            // than blocking the removal the user asked for.
        }
    };

    return (
        <div className="life-field attachment-field">
            <span className="life-field-label">
                <Paperclip size={12} /> {label} <em>{hint}</em>
            </span>
            <div className="attachment-list">
                {attachments.map((attachment) => (
                    <AttachmentItem key={attachment.id} attachment={attachment} onRemove={remove} />
                ))}
                <button
                    type="button"
                    className="attachment-add"
                    onClick={() => inputRef.current?.click()}
                    disabled={disabled || uploading || !ownerId || attachments.length >= MAX_ATTACHMENTS_PER_RECORD}
                >
                    {uploading ? (
                        <>
                            <Loader2 size={13} className="spin" /> Uploading…
                        </>
                    ) : (
                        <>
                            <Paperclip size={13} /> Add file
                        </>
                    )}
                </button>
                <input
                    ref={inputRef}
                    type="file"
                    accept="image/*,application/pdf,.doc,.docx,.xls,.xlsx,.txt,.csv"
                    multiple
                    hidden
                    onChange={pickFiles}
                />
            </div>
            {error && (
                <span className="attachment-error" role="alert">
                    {error}
                </span>
            )}
        </div>
    );
}
