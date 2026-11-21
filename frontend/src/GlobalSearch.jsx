import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    ArrowLeftRight, BookOpen, CheckSquare, FileText, Search, X, CornerDownLeft,
} from 'lucide-react';

/**
 * Global search — one field over the whole workspace.
 * Results are grouped by the kind of record (pages, transactions, notes,
 * tasks, journal) and each row reports what it is plus where it lives.
 */
const GROUP_META = {
    pages: { label: 'Pages', icon: FileText },
    transactions: { label: 'Transactions', icon: ArrowLeftRight },
    notes: { label: 'Notes', icon: FileText },
    tasks: { label: 'Tasks', icon: CheckSquare },
    journal: { label: 'Journal', icon: BookOpen },
};

export default function GlobalSearch({
    query,
    onQuery,
    groups,
    onPick,
    expanded = false,
    onClose,
    placeholder = 'Search transactions, notes, tasks, journal…',
}) {
    const [open, setOpen] = useState(false);
    const [active, setActive] = useState(0);
    const wrapRef = useRef(null);
    const inputRef = useRef(null);

    // Focusing when the phone header expands the field.
    useEffect(() => {
        if (expanded) inputRef.current?.focus();
    }, [expanded]);

    // Escape closes the expanded phone search, results included.
    useEffect(() => {
        if (!expanded) return undefined;
        const onKey = e => {
            if (e.key === 'Escape') { setOpen(false); onClose?.(); }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [expanded, onClose]);

    const flat = useMemo(() => groups.flatMap(g => g.items.map(item => ({ ...item, group: g.id }))), [groups]);
    const total = flat.length;
    const hasQuery = query.trim().length > 0;

    useEffect(() => { setActive(0); }, [query]);

    useEffect(() => {
        const onDoc = e => {
            if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
        };
        const onKey = e => { if (e.key === 'Escape') setOpen(false); };
        document.addEventListener('mousedown', onDoc);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onDoc);
            document.removeEventListener('keydown', onKey);
        };
    }, []);

    const pick = index => {
        const item = flat[index];
        if (!item) return;
        onPick(item);
        setOpen(false);
        inputRef.current?.blur();
    };

    const onKeyDown = e => {
        if (!open) {
            if (e.key === 'ArrowDown' && hasQuery) setOpen(true);
            return;
        }
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActive(i => (i + 1) % Math.max(1, total));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActive(i => (i - 1 + total) % Math.max(1, total));
        } else if (e.key === 'Enter') {
            e.preventDefault();
            pick(active);
        } else if (e.key === 'Escape') {
            setOpen(false);
        }
    };

    let cursor = -1;

    return (
        <div className="gsearch" ref={wrapRef}>
            <label className={`search${open && hasQuery ? ' is-open' : ''}`}>
                <Search size={16} />
                <input
                    ref={inputRef}
                    value={query}
                    placeholder={placeholder}
                    onChange={e => {
                        onQuery(e.target.value);
                        setOpen(true);
                    }}
                    onFocus={() => { if (hasQuery) setOpen(true); }}
                    onKeyDown={onKeyDown}
                    aria-label="Search the workspace"
                    aria-expanded={open}
                    aria-controls="gsearch-results"
                />
                {query && (
                    <button
                        type="button"
                        className="gsearch-clear"
                        onClick={() => { onQuery(''); setOpen(false); inputRef.current?.focus(); }}
                        title="Clear search"
                        aria-label="Clear search"
                    >
                        <X size={13} />
                    </button>
                )}
            </label>

            {open && hasQuery && (
                <div className="gsearch-panel" id="gsearch-results" role="listbox">
                    {total === 0 ? (
                        <div className="gsearch-empty">
                            <b>No matches for “{query.trim()}”</b>
                            <span>Try an amount, a merchant, a note title or a task.</span>
                        </div>
                    ) : (
                        groups.filter(g => g.items.length).map(group => {
                            const meta = GROUP_META[group.id] || { label: group.id, icon: FileText };
                            const Icon = meta.icon;
                            return (
                                <section className="gsearch-group" key={group.id}>
                                    <header>
                                        <span>{meta.label}</span>
                                        <b>{group.items.length}</b>
                                    </header>
                                    {group.items.map(item => {
                                        cursor += 1;
                                        const index = cursor;
                                        return (
                                            <button
                                                type="button"
                                                key={`${group.id}-${item.id}`}
                                                role="option"
                                                aria-selected={index === active}
                                                className={`gsearch-item${index === active ? ' is-active' : ''}`}
                                                onMouseEnter={() => setActive(index)}
                                                onClick={() => pick(index)}
                                            >
                                                <i className="gsearch-icon"><Icon size={14} /></i>
                                                <span className="gsearch-text">
                                                    <b>{item.title}</b>
                                                    {item.subtitle && <small>{item.subtitle}</small>}
                                                </span>
                                                {item.meta && <span className="gsearch-meta">{item.meta}</span>}
                                            </button>
                                        );
                                    })}
                                </section>
                            );
                        })
                    )}

                    <footer className="gsearch-foot">
                        <span><CornerDownLeft size={12} /> open</span>
                        <span>↑↓ move</span>
                        <span>esc close</span>
                    </footer>
                </div>
            )}
        </div>
    );
}
