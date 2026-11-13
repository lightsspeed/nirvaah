import React, { useEffect, useMemo, useState } from 'react';
import {
    Plus, BookOpen, CalendarDays, Pencil, Trash2, Sparkles, Activity,
    IndianRupee, Wallet, StickyNote, ListChecks, Settings2, SlidersHorizontal,
    CircleDot,
} from 'lucide-react';
import {
    useCollection, useActivity, logActivity, clearActivity, uid, todayISO,
    formatDay, shortDay, monthKey, monthLabel, timeAgo, moodMeta,
    EVENTS_KEY, tintOf, categoryPool, useCategories,
} from './store';
import { parseDateOnly, yearOf } from '../dates';
import { PageHero, StatTile, Chip, SearchField, Segmented, EmptyState, Modal, CategoryManager } from './ui';

const MOODS = ['great', 'good', 'steady', 'low', 'hard'];

const ACTIVITY_TYPES = {
    money: { label: 'Money', tint: '#d97757', icon: IndianRupee },
    expense: { label: 'Money', tint: '#d97757', icon: IndianRupee },
    income: { label: 'Money', tint: '#7fa650', icon: Wallet },
    note: { label: 'Notes', tint: '#a78bd0', icon: StickyNote },
    task: { label: 'Tasks', tint: '#7fa650', icon: ListChecks },
    system: { label: 'System', tint: '#a89f94', icon: Settings2 },
    filter: { label: 'Filters', tint: '#6a9bd0', icon: SlidersHorizontal },
    auth: { label: 'Account', tint: '#c9a227', icon: Sparkles },
};
const activityMeta = type => ACTIVITY_TYPES[type] || ACTIVITY_TYPES.system;

const emptyEvent = () => ({
    id: uid(),
    title: '',
    description: '',
    category: 'Life',
    mood: 'steady',
    amount: '',
    tags: [],
    date: todayISO(),
    createdAt: Date.now(),
});

function EventEditor({ event, onClose, onSave, onDelete }) {
    const [cats] = useCategories('event');
    const pool = useMemo(() => categoryPool(cats, [event]), [cats, event]);
    const [draft, setDraft] = useState(() => ({ ...event, tagsText: (event.tags || []).join(', ') }));
    const isNew = !event.title;

    useEffect(() => {
        const onKey = e => {
            if (e.key === 'Escape') onClose();
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); submit(); }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    });

    const submit = () => {
        const tags = draft.tagsText.split(',').map(x => x.trim().replace(/^#/, '')).filter(Boolean);
        onSave({
            ...draft,
            title: draft.title.trim() || 'Untitled event',
            tags,
            amount: draft.amount === '' ? '' : Number(draft.amount),
        });
    };

    return (
        <Modal
            title={isNew ? 'Log a life event' : 'Edit event'}
            subtitle={isNew ? 'JOURNAL' : formatDay(event.date).toUpperCase()}
            onClose={onClose}
            wide
            footer={(
                <>
                    <div className="life-modal-left">
                        {!isNew && (
                            <button type="button" className="life-btn is-ghost is-danger" onClick={() => onDelete(event)}>
                                <Trash2 size={14} /> Delete
                            </button>
                        )}
                    </div>
                    <span className="kbd-hint">⌘ + Enter to save</span>
                    <button type="button" className="life-btn" onClick={onClose}>Cancel</button>
                    <button type="button" className="life-btn is-primary" onClick={submit}>
                        <Pencil size={14} /> {isNew ? 'Log event' : 'Save changes'}
                    </button>
                </>
            )}
        >
            <div className="journal-editor-grid">
                <label className="life-field">
                    <span className="life-field-label">What happened</span>
                    <input
                        className="note-title-input"
                        placeholder="e.g. Closed the home loan prepayment"
                        value={draft.title}
                        onChange={e => setDraft({ ...draft, title: e.target.value })}
                        autoFocus
                    />
                </label>
                <label className="life-field is-compact">
                    <span className="life-field-label">Date</span>
                    <input
                        className="life-input"
                        type="date"
                        value={draft.date}
                        onChange={e => setDraft({ ...draft, date: e.target.value })}
                    />
                </label>
            </div>

            <div className="life-field">
                <span className="life-field-label">Category</span>
                <div className="life-chip-row">
                    {pool.map(cat => (
                        <Chip key={cat} label={cat} active={draft.category === cat} onClick={() => setDraft({ ...draft, category: cat })} />
                    ))}
                </div>
            </div>

            <div className="life-field">
                <span className="life-field-label">How did it feel</span>
                <div className="mood-row">
                    {MOODS.map(m => {
                        const meta = moodMeta(m);
                        return (
                            <button
                                key={m}
                                type="button"
                                className={`mood-btn${draft.mood === m ? ' is-active' : ''}`}
                                style={{ '--chip': meta.tint }}
                                onClick={() => setDraft({ ...draft, mood: m })}
                                title={meta.label}
                            >
                                <span>{meta.glyph}</span>{meta.label}
                            </button>
                        );
                    })}
                </div>
            </div>

            <div className="journal-editor-grid">
                <label className="life-field">
                    <span className="life-field-label"><IndianRupee size={12} /> Money involved <em>optional</em></span>
                    <input
                        className="life-input"
                        inputMode="decimal"
                        placeholder="0"
                        value={draft.amount}
                        onChange={e => setDraft({ ...draft, amount: e.target.value.replace(/[^\d.]/g, '') })}
                    />
                </label>
                <label className="life-field">
                    <span className="life-field-label">Tags <em>comma separated</em></span>
                    <input
                        className="life-input"
                        placeholder="family, loan, milestone"
                        value={draft.tagsText}
                        onChange={e => setDraft({ ...draft, tagsText: e.target.value })}
                    />
                </label>
            </div>

            <label className="life-field">
                <span className="life-field-label">Details</span>
                <textarea
                    className="life-textarea"
                    rows={6}
                    placeholder="Context, numbers, who was there, what changes now…"
                    value={draft.description}
                    onChange={e => setDraft({ ...draft, description: e.target.value })}
                />
            </label>
        </Modal>
    );
}

export default function JournalPage() {
    const [events, setEvents] = useCollection(EVENTS_KEY);
    const [cats, setCats] = useCategories('event');
    const pool = useMemo(() => categoryPool(cats, events), [cats, events]);
    const [manageCats, setManageCats] = useState(false);
    const activity = useActivity();
    const [tab, setTab] = useState('events');
    const [query, setQuery] = useState('');
    const [category, setCategory] = useState('All');
    const [year, setYear] = useState('All');
    const [typeFilter, setTypeFilter] = useState('all');
    const [editing, setEditing] = useState(null);

    const years = useMemo(() => {
        const set = new Set(events.map(e => yearOf(e.date)).filter(y => y !== null));
        return ['All', ...[...set].sort((a, b) => b - a).map(String)];
    }, [events]);

    const stats = useMemo(() => {
        const thisMonth = monthKey(Date.now());
        const inMonth = events.filter(e => monthKey(e.date) === thisMonth);
        const money = events.reduce((sum, e) => sum + (Number(e.amount) || 0), 0);
        const byCat = {};
        events.forEach(e => { byCat[e.category] = (byCat[e.category] || 0) + 1; });
        const top = Object.entries(byCat).sort((a, b) => b[1] - a[1])[0];
        return { inMonth: inMonth.length, total: events.length, money, top: top ? top[0] : '—' };
    }, [events]);

    const catCounts = useMemo(() => {
        const map = { All: events.length };
        pool.forEach(c => { map[c] = events.filter(e => e.category === c).length; });
        return map;
    }, [events]);

    const visible = useMemo(() => {
        let list = events;
        if (category !== 'All') list = list.filter(e => e.category === category);
        if (year !== 'All') list = list.filter(e => String(yearOf(e.date)) === year);
        if (query.trim()) {
            const q = query.trim().toLowerCase();
            list = list.filter(e =>
                e.title.toLowerCase().includes(q) ||
                e.description.toLowerCase().includes(q) ||
                e.category.toLowerCase().includes(q) ||
                e.tags.some(t => t.toLowerCase().includes(q))
            );
        }
        return [...list].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : b.createdAt - a.createdAt));
    }, [events, category, year, query]);

    const months = useMemo(() => {
        const groups = [];
        visible.forEach(e => {
            const key = monthKey(e.date);
            const last = groups[groups.length - 1];
            if (last && last.key === key) last.items.push(e);
            else groups.push({ key, items: [e] });
        });
        return groups;
    }, [visible]);

    const activityVisible = useMemo(() => {
        if (typeFilter === 'all') return activity;
        return activity.filter(a => (ACTIVITY_TYPES[a.type]?.label || 'System').toLowerCase() === typeFilter);
    }, [activity, typeFilter]);

    const activityDays = useMemo(() => {
        const groups = [];
        activityVisible.forEach(a => {
            const key = new Date(a.at).toDateString();
            const last = groups[groups.length - 1];
            if (last && last.key === key) last.items.push(a);
            else groups.push({ key, items: [a] });
        });
        return groups;
    }, [activityVisible]);

    const saveEvent = draft => {
        const exists = events.some(e => e.id === draft.id);
        setEvents(prev => exists ? prev.map(e => e.id === draft.id ? draft : e) : [draft, ...prev]);
        logActivity(exists ? `Life event updated: “${draft.title}”` : `Life event logged: “${draft.title}”`, 'system', draft.category);
        setEditing(null);
    };

    const deleteEvent = event => {
        if (!window.confirm(`Delete “${event.title}” from your journal?`)) return;
        setEvents(prev => prev.filter(e => e.id !== event.id));
        logActivity(`Life event removed: “${event.title}”`, 'system');
        setEditing(null);
    };

    const dayLabel = key => {
        const d = new Date(key);
        const todayD = new Date();
        const yest = new Date(); yest.setDate(yest.getDate() - 1);
        if (d.toDateString() === todayD.toDateString()) return 'Today';
        if (d.toDateString() === yest.toDateString()) return 'Yesterday';
        return formatDay(d.getTime());
    };

    return (
        <div className="life-page journal-page">
            <PageHero>
                <button type="button" className="life-btn is-primary" onClick={() => setEditing(emptyEvent())}>
                    <Plus size={15} /> Log event
                </button>
            </PageHero>

            <div className="life-stats">
                <StatTile label="This month" value={stats.inMonth} hint="Moments logged in the current month" icon={CalendarDays} tint="#d97757" />
                <StatTile label="All events" value={stats.total} hint="Your running life timeline" icon={BookOpen} tint="#c9a227" />
                <StatTile label="Money touched" value={stats.money ? `₹${stats.money.toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'} hint="Sum of amounts attached to events" icon={IndianRupee} tint="#7fa650" />
                <StatTile label="Most logged" value={stats.top} hint="Category with the most entries" icon={CircleDot} tint="#6a9bd0" />
            </div>

            <div className="life-toolbar">
                <Segmented
                    options={[
                        { id: 'events', label: 'Life events', count: events.length },
                        { id: 'activity', label: 'Activity', count: activity.length },
                    ]}
                    value={tab}
                    onChange={setTab}
                />
                {tab === 'events' ? (
                    <div className="life-toolbar-right">
                        <label className="life-select">
                            <span>Year</span>
                            <select value={year} onChange={e => setYear(e.target.value)}>
                                {years.map(y => <option key={y} value={y}>{y === 'All' ? 'All years' : y}</option>)}
                            </select>
                        </label>
                    </div>
                ) : (
                    <div className="life-toolbar-right">
                        <button type="button" className="life-toggle" onClick={() => { if (window.confirm('Clear the activity history?')) clearActivity(); }}>
                            <Trash2 size={13} /> Clear history
                        </button>
                    </div>
                )}
            </div>

            {tab === 'events' && (
                <div className="life-chip-row">
                    <Chip label="All" active={category === 'All'} count={catCounts.All} onClick={() => setCategory('All')} tint="#a89f94" />
                    {pool.map(c => (
                        <Chip key={c} label={c} active={category === c} count={catCounts[c]} onClick={() => setCategory(c)} />
                    ))}
                    <button type="button" className="life-chip is-manage" onClick={() => setManageCats(true)} title="Add, rename or delete categories">
                        <SlidersHorizontal size={13} /><span>Manage</span>
                    </button>
                </div>
            )}

            {tab === 'events' ? (
                visible.length === 0 ? (
                    <EmptyState
                        icon={BookOpen}
                        title={query || category !== 'All' ? 'No events match' : 'Start your timeline'}
                        hint={query || category !== 'All' ? 'Try another category, year or search word.' : 'Log a purchase, a milestone, a hard day — the context money never captures.'}
                        action={!query && category === 'All' && (
                            <button type="button" className="life-btn is-primary" onClick={() => setEditing(emptyEvent())}>
                                <Plus size={14} /> Log your first event
                            </button>
                        )}
                    />
                ) : (
                    <div className="task-list journal-rows">
                        {months.map(group => (
                            <section key={group.key} className="task-group">
                                <div className="task-group-head" style={{ '--group': 'var(--primary)' }}>
                                    <span>{monthLabel(group.key)}</span>
                                    <i />
                                    <b>{group.items.length}</b>
                                </div>
                                {group.items.map(event => {
                                    const mood = moodMeta(event.mood);
                                    const day = parseDateOnly(event.date);
                                    return (
                                        <div
                                            key={event.id}
                                            className="task-row journal-row"
                                            role="button"
                                            tabIndex={0}
                                            onClick={() => setEditing(event)}
                                            onKeyDown={e => { if (e.key === 'Enter') setEditing(event); }}
                                        >
                                            <span className="journal-day" style={{ '--chip': tintOf(event.category) }}>
                                                <b>{day ? day.getDate() : '—'}</b>
                                                <small>{day ? day.toLocaleDateString('en-IN', { month: 'short' }) : ''}</small>
                                            </span>
                                            <div className="task-main">
                                                <span className="task-text">{event.title}</span>
                                                <div className="task-meta">
                                                    <span className="task-cat" style={{ '--chip': tintOf(event.category) }}><i />{event.category}</span>
                                                    <span className="task-due"><CalendarDays size={11} /> {shortDay(event.date)}</span>
                                                    {event.description && (
                                                        <span className="task-note-dot" title={event.description}><StickyNote size={11} /></span>
                                                    )}
                                                    {event.tags.map(t => <span key={t} className="task-tag">#{t}</span>)}
                                                    {Number(event.amount) > 0 && (
                                                        <span className="task-amount"><IndianRupee size={11} />{Number(event.amount).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>
                                                    )}
                                                    <span className="task-age">{timeAgo(event.createdAt)}</span>
                                                </div>
                                            </div>
                                            <span className="task-prio" style={{ '--chip': mood.tint }} title={`Feeling ${mood.label}`}>
                                                {mood.label}
                                            </span>
                                            <div className="task-actions" onClick={e => e.stopPropagation()}>
                                                <button type="button" className="life-icon-btn" title="Edit entry" onClick={() => setEditing(event)}>
                                                    <Pencil size={13} />
                                                </button>
                                                <button type="button" className="life-icon-btn is-danger" title="Delete entry" onClick={() => deleteEvent(event)}>
                                                    <Trash2 size={13} />
                                                </button>
                                            </div>
                                        </div>
                                    );
                                })}
                            </section>
                        ))}
                    </div>
                )
            ) : (
                <>
                    <div className="life-chip-row">
                        {['all', 'money', 'notes', 'tasks', 'system', 'account'].map(id => (
                            <Chip
                                key={id}
                                label={id === 'all' ? 'All activity' : id.charAt(0).toUpperCase() + id.slice(1)}
                                active={typeFilter === id}
                                onClick={() => setTypeFilter(id)}
                                tint={id === 'all' ? '#a89f94' : activityMeta(id === 'money' ? 'money' : id === 'account' ? 'auth' : id.slice(0, -1)).tint}
                                dot={id !== 'all'}
                            />
                        ))}
                    </div>
                    {activityDays.length === 0 ? (
                        <EmptyState icon={Activity} title="No activity yet" hint="Actions across Nirvaah will appear here as they happen." />
                    ) : (
                        <div className="activity-stream">
                            {activityDays.map(day => (
                                <section key={day.key}>
                                    <div className="activity-day">{dayLabel(day.key)}</div>
                                    {day.items.map(entry => {
                                        const meta = activityMeta(entry.type);
                                        const Icon = meta.icon || Activity;
                                        return (
                                            <div key={entry.id} className="activity-row" style={{ '--chip': meta.tint }}>
                                                <i><Icon size={13} strokeWidth={1.8} /></i>
                                                <div>
                                                    <b>{entry.action}</b>
                                                    {entry.detail && <small>{entry.detail}</small>}
                                                </div>
                                                <span>{timeAgo(entry.at)}</span>
                                            </div>
                                        );
                                    })}
                                </section>
                            ))}
                        </div>
                    )}
                </>
            )}

            {editing && (
                <EventEditor
                    event={editing}
                    onClose={() => setEditing(null)}
                    onSave={saveEvent}
                    onDelete={deleteEvent}
                />
            )}

            <CategoryManager
                open={manageCats}
                onClose={() => setManageCats(false)}
                title="Journal categories"
                categories={pool}
                onChange={setCats}
                onRename={(from, to) => setEvents(prev => prev.map(e => (e.category === from ? { ...e, category: to } : e)))}
                onDelete={cat => {
                    const fallback = pool.find(c => c !== cat) || 'Life';
                    setEvents(prev => prev.map(e => (e.category === cat ? { ...e, category: fallback } : e)));
                    if (category === cat) setCategory('All');
                }}
            />
        </div>
    );
}
