import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, X } from 'lucide-react';

/* ── In-app confirmation ─────────────────────────────────────────────────────
   Every destructive action in Nirvaah asks through this dialog instead of
   window.confirm(). `ask()` returns a promise, so existing handlers keep their
   shape:

       const { ask, dialog } = useConfirm();
       if (!(await ask({ title: `Delete “${note.title}”?`, ... }))) return;
       ...delete...
       {dialog}

   Only one dialog is live at a time; a second ask() replaces the first and the
   earlier promise resolves false, so a stale confirmation can never approve a
   different operation.
*/

const BASE = {
    title: 'Delete this record?',
    message: '',
    note: '',
    confirmLabel: 'Delete',
    cancelLabel: 'Cancel',
    tone: 'danger',
};

export function ConfirmDialog({ request, onCancel, onConfirm }) {
    const cancelRef = useRef(null);
    const restoreRef = useRef(null);

    useEffect(() => {
        if (!request) return undefined;
        restoreRef.current = document.activeElement;
        cancelRef.current?.focus();
        const onKey = event => {
            if (event.key === 'Escape') {
                event.preventDefault();
                onCancel();
            }
        };
        window.addEventListener('keydown', onKey);
        return () => {
            window.removeEventListener('keydown', onKey);
            if (restoreRef.current && document.contains(restoreRef.current)) {
                restoreRef.current.focus?.();
            }
        };
    }, [request, onCancel]);

    if (!request) return null;

    const { title, message, note, confirmLabel, cancelLabel, tone } = request;

    return createPortal(
        <div
            className="confirm-layer"
            onMouseDown={event => { if (event.target === event.currentTarget) onCancel(); }}
        >
            <div
                className="confirm-card"
                role="alertdialog"
                aria-modal="true"
                aria-labelledby="confirm-title"
                aria-describedby={message ? 'confirm-message' : undefined}
            >
                <span className={`confirm-icon is-${tone}`} aria-hidden="true">
                    <AlertTriangle size={17} />
                </span>

                <div className="confirm-copy">
                    <h3 id="confirm-title">{title}</h3>
                    {message && <p id="confirm-message">{message}</p>}
                    {note && <p className="confirm-note">{note}</p>}
                </div>

                <button type="button" className="confirm-close" onClick={onCancel} aria-label="Close">
                    <X size={15} />
                </button>

                <div className="confirm-actions">
                    <button type="button" className="life-btn" ref={cancelRef} onClick={onCancel}>
                        {cancelLabel}
                    </button>
                    <button
                        type="button"
                        className={`life-btn ${tone === 'danger' ? 'is-danger-solid' : 'is-primary'}`}
                        onClick={onConfirm}
                    >
                        {confirmLabel}
                    </button>
                </div>
            </div>
        </div>,
        document.body
    );
}

export function useConfirm() {
    const [request, setRequest] = useState(null);
    const resolver = useRef(null);

    const ask = useCallback(options => new Promise(resolve => {
        resolver.current?.(false);           // a replaced dialog never confirms
        resolver.current = resolve;
        setRequest({ ...BASE, ...(typeof options === 'string' ? { message: options } : options) });
    }), []);

    const settle = useCallback(answer => {
        setRequest(null);
        const resolve = resolver.current;
        resolver.current = null;
        resolve?.(answer);
    }, []);

    const dialog = (
        <ConfirmDialog
            request={request}
            onCancel={() => settle(false)}
            onConfirm={() => settle(true)}
        />
    );

    return { ask, dialog };
}

export default ConfirmDialog;
