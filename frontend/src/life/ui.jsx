import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, Plus, Search, Trash2, X } from 'lucide-react';
import { tintOf } from './store';
import { useConfirm } from '../ConfirmDialog';

export function PageHero({ title, description, children }) {
    // The page name and its subtext live in the app header now; the hero only
    // keeps copy for views that need their own title (a task project).
    const hasCopy = Boolean(title || description);
    const [phone, setPhone] = useState(
        () => typeof window !== 'undefined' && window.matchMedia('(max-width: 640px)').matches
    );
    const [slot, setSlot] = useState(null);

    useEffect(() => {
        const query = window.matchMedia('(max-width: 640px)');
        const sync = () => setPhone(query.matches);
        sync();
        query.addEventListener('change', sync);
        return () => query.removeEventListener('change', sync);
    }, []);

    useEffect(() => {
        setSlot(phone ? document.getElementById('page-header-actions') : null);
    }, [phone, hasCopy]);

    const actions = children ? <div className="life-hero-actions">{children}</div> : null;

    // Phones carry the page action in the header, beside the search, so it does
    // not consume a row of its own above the content.
    if (phone && !hasCopy) {
        return slot && actions ? createPortal(actions, slot) : null;
    }

    return (
        <header className={`life-hero${hasCopy ? '' : ' is-actions-only'}`}>
            {hasCopy && (
                <div className="life-hero-copy">
                    {title && <h1>{title}</h1>}
                    {description && <p>{description}</p>}
                </div>
            )}
            {actions && (phone ? (slot ? createPortal(actions, slot) : null) : actions)}
        </header>
    );
}

export function StatTile({ label, value, hint, icon: Icon, tint = '#d97757' }) {
    return (
        <div className="life-stat" style={{ '--tile': tint }}>
            <div className="life-stat-top">
                <span>{label}</span>
                {Icon && <i><Icon size={14} strokeWidth={1.8} /></i>}
            </div>
            <strong>{value}</strong>
            {hint && <small>{hint}</small>}
        </div>
    );
}

export function Chip({ label, active, count, onClick, tint, dot = false }) {
    const color = tint || tintOf(label);
    return (
        <button
            type="button"
            onClick={onClick}
            className={`life-chip${active ? ' is-active' : ''}`}
            style={{ '--chip': color }}
        >
            {dot && <i className="life-chip-dot" />}
            <span>{label}</span>
            {count != null && <b>{count}</b>}
        </button>
    );
}

export function SearchField({ value, onChange, placeholder }) {
    return (
        <label className="life-search">
            <Search size={15} strokeWidth={2} />
            <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} />
            {value && (
                <button type="button" onClick={() => onChange('')} title="Clear search">
                    <X size={13} />
                </button>
            )}
        </label>
    );
}

export function Segmented({ options, value, onChange }) {
    return (
        <div className="life-segmented" role="tablist">
            {options.map(opt => (
                <button
                    key={opt.id}
                    type="button"
                    role="tab"
                    aria-selected={value === opt.id}
                    className={value === opt.id ? 'is-active' : ''}
                    onClick={() => onChange(opt.id)}
                >
                    {opt.label}
                    {opt.count != null && <b>{opt.count}</b>}
                </button>
            ))}
        </div>
    );
}

export function EmptyState({ icon: Icon, title, hint, action }) {
    return (
        <div className="life-empty">
            {Icon && <i><Icon size={22} strokeWidth={1.5} /></i>}
            <h3>{title}</h3>
            {hint && <p>{hint}</p>}
            {action}
        </div>
    );
}

export function Modal({ title, subtitle, onClose, children, footer, wide }) {
    return createPortal(
        <div className="life-modal-layer" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
            <div className={`life-modal${wide ? ' is-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
                <header>
                    <div>
                        <small>{subtitle}</small>
                        <h2>{title}</h2>
                    </div>
                    <button type="button" className="life-icon-btn" onClick={onClose} title="Close (Esc)">
                        <X size={16} />
                    </button>
                </header>
                <div className="life-modal-body">{children}</div>
                {footer && <footer>{footer}</footer>}
            </div>
        </div>,
        document.body
    );
}

export function Progress({ value, tint = '#7fa650' }) {
    return (
        <div className="life-progress" aria-hidden="true">
            <i style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: tint }} />
        </div>
    );
}

/* ── Category (tab) manager ────────────────────────────────────────────────
   Add, rename and delete the category list a page filters by. Renames and
   deletions are reported back so the page can move its own records. */
export function CategoryManager({ open, onClose, title = 'Manage categories', categories, onChange, onRename, onDelete }) {
    const [draft, setDraft] = useState('');
    const [edits, setEdits] = useState({});
    const { ask, dialog } = useConfirm();

    useEffect(() => {
        if (!open) { setDraft(''); setEdits({}); }
    }, [open]);

    if (!open) return null;

    const commit = (from, to) => {
        const next = String(to || '').trim();
        if (!next || next === from) { setEdits(e => ({ ...e, [from]: undefined })); return; }
        if (categories.some(c => c.toLowerCase() === next.toLowerCase())) return;
        onChange(categories.map(c => (c === from ? next : c)));
        onRename && onRename(from, next);
        setEdits(e => ({ ...e, [from]: undefined }));
    };

    const remove = async cat => {
        if (categories.length <= 1) return;
        const fallback = categories.find(c => c !== cat);
        const ok = await ask({
            title: `Delete the “${cat}” category?`,
            message: `Records filed under it move to “${fallback}”. Nothing else is deleted.`,
            confirmLabel: 'Delete category',
        });
        if (!ok) return;
        onChange(categories.filter(c => c !== cat));
        onDelete && onDelete(cat);
    };

    const add = e => {
        e.preventDefault();
        const name = draft.trim();
        if (!name || categories.some(c => c.toLowerCase() === name.toLowerCase())) return;
        onChange([...categories, name]);
        setDraft('');
    };

    return (
        <Modal
            title={title}
            subtitle="ADD · RENAME · DELETE"
            onClose={onClose}
            footer={
                <>
                    <button type="button" className="life-btn is-ghost" onClick={onClose}>Cancel</button>
                    <button type="button" className="life-btn is-primary" onClick={onClose}>Done</button>
                </>
            }
        >
            <form className="cat-manage-add" onSubmit={add}>
                <input
                    className="life-input"
                    placeholder="New category name…"
                    value={draft}
                    onChange={e => setDraft(e.target.value)}
                />
                <button type="submit" className="life-btn is-primary" disabled={!draft.trim()}>
                    <Plus size={14} /> Add
                </button>
            </form>

            <div className="cat-manage-list">
                {categories.map(cat => (
                    <div className="cat-manage-row" key={cat}>
                        <input
                            className="life-input"
                            value={edits[cat] !== undefined ? edits[cat] : cat}
                            onChange={e => setEdits(s => ({ ...s, [cat]: e.target.value }))}
                            onBlur={e => commit(cat, e.target.value)}
                            onKeyDown={e => {
                                if (e.key === 'Enter') { e.preventDefault(); commit(cat, e.target.value); e.currentTarget.blur(); }
                                if (e.key === 'Escape') { setEdits(s => ({ ...s, [cat]: undefined })); e.currentTarget.blur(); }
                            }}
                        />
                        <button
                            type="button"
                            className="life-icon-btn is-danger"
                            title={`Delete "${cat}"`}
                            disabled={categories.length <= 1}
                            onClick={() => remove(cat)}
                        >
                            <Trash2 size={14} />
                        </button>
                    </div>
                ))}
            </div>
            <p className="cat-manage-hint">
                Renaming or deleting a category moves its records to the first remaining one.
            </p>
            {dialog}
        </Modal>
    );
}

/* ── Select ────────────────────────────────────────────────────────────────
   The app's dropdown, rendered as a labelled field: same trigger height,
   radius and menu as every CustomSelect elsewhere. */
export function Select({ label, value, onChange, options, placeholder = 'Select…', compact = false, className = '' }) {
    const [open, setOpen] = useState(false);
    const [pos, setPos] = useState(null);
    const ref = useRef(null);
    const buttonRef = useRef(null);
    const menuRef = useRef(null);
    const norm = options.map(o => (typeof o === 'string' ? { value: o, label: o } : o));
    const selected = norm.find(o => o.value === value);

    // Anchored to the viewport so the menu can leave a scrolling editor or a
    // clipped row, and clamped so it never runs off the bottom of the screen.
    const place = () => {
        const button = buttonRef.current;
        if (!button) return;
        const r = button.getBoundingClientRect();
        const gap = 6;
        const spaceBelow = window.innerHeight - r.bottom - 12;
        const spaceAbove = r.top - 12;
        const up = spaceBelow < 300 && spaceAbove > spaceBelow;
        const width = Math.min(r.width, window.innerWidth - 24);
        let left = r.left;
        if (left + width > window.innerWidth - 12) left = Math.max(12, window.innerWidth - width - 12);
        setPos({
            left,
            width,
            maxHeight: Math.min(300, Math.max(96, (up ? spaceAbove : spaceBelow) - gap)),
            ...(up ? { bottom: window.innerHeight - r.top + gap } : { top: r.bottom + gap }),
        });
    };

    useEffect(() => {
        const onDoc = e => {
            const inWrap = ref.current && ref.current.contains(e.target);
            const inMenu = menuRef.current && menuRef.current.contains(e.target);
            if (!inWrap && !inMenu) setOpen(false);
        };
        document.addEventListener('mousedown', onDoc);
        return () => document.removeEventListener('mousedown', onDoc);
    }, []);

    useEffect(() => {
        if (!open) return;
        const onMove = () => place();
        window.addEventListener('scroll', onMove, true);
        window.addEventListener('resize', onMove);
        return () => {
            window.removeEventListener('scroll', onMove, true);
            window.removeEventListener('resize', onMove);
        };
    }, [open]);

    const toggle = () => {
        if (!open) place();
        setOpen(v => !v);
    };

    return (
        <div className={`life-select-wrap${compact ? ' is-compact' : ''}${className ? ` ${className}` : ''}`} ref={ref}>
            <button
                ref={buttonRef}
                type="button"
                className={`life-select as-button${open ? ' is-open' : ''}`}
                onClick={toggle}
                aria-haspopup="listbox"
                aria-expanded={open}
            >
                <span>{label}</span>
                <b>{selected ? selected.label : placeholder}</b>
                <ChevronDown size={14} className="life-select-chevron" />
            </button>

            {open && createPortal(
                <div
                    ref={menuRef}
                    className="custom-select-menu life-select-menu is-fixed"
                    role="listbox"
                    style={pos ? {
                        '--menu-left': `${pos.left}px`,
                        '--menu-w': `${pos.width}px`,
                        '--menu-maxh': `${pos.maxHeight}px`,
                        '--menu-top': pos.top != null ? `${pos.top}px` : 'auto',
                        '--menu-bottom': pos.bottom != null ? `${pos.bottom}px` : 'auto',
                    } : undefined}
                >
                    {norm.map(opt => (
                        <button
                            key={opt.value}
                            type="button"
                            role="option"
                            aria-selected={opt.value === value}
                            className={`custom-select-item${opt.value === value ? ' selected' : ''}`}
                            onClick={() => { onChange(opt.value); setOpen(false); }}
                        >
                            <span>{opt.label}</span>
                            {opt.value === value && <Check size={14} className="item-check" />}
                        </button>
                    ))}
                </div>,
                document.body
            )}
        </div>
    );
}
