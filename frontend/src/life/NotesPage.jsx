import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    Plus, FileText, Pin, Archive, ArchiveRestore, Trash2, PencilLine,
    Undo2, NotebookPen, Tag, SlidersHorizontal, Paperclip,
} from 'lucide-react';
import {
    useCollection, logActivity, uid, timeAgo, wordCount, formatDay,
    NOTES_KEY, tintOf, categoryPool, useCategories,
} from './store';
import { PageHero, StatTile, Chip, EmptyState, Modal, CategoryManager, Select } from './ui';
import AttachmentField from './AttachmentField';
import { deleteAttachment } from './attachments';
import { useConfirm } from '../ConfirmDialog';

const SORTS = [
    { id: 'updated', label: 'Recently edited' },
    { id: 'created', label: 'Newest first' },
    { id: 'title', label: 'Title A–Z' },
];

const emptyDraft = () => ({
    id: uid(),
    title: '',
    body: '',
    category: 'Personal',
    tags: [],
    attachments: [],
    pinned: false,
    archived: false,
    createdAt: Date.now(),
    updatedAt: Date.now(),
});

function NoteCard({ note, onOpen, onTogglePin, onToggleArchive, onDelete }) {
    return (
        <article
            className={`note-card${note.pinned ? ' is-pinned' : ''}`}
            style={{ '--note-tint': tintOf(note.category) }}
            onClick={() => onOpen(note)}
            onKeyDown={e => { if (e.key === 'Enter') onOpen(note); }}
            tabIndex={0}
            role="button"
            aria-label={`Open note ${note.title}`}
        >
            <div className="note-card-top">
                <span className="note-cat"><i />{note.category}</span>
                <div className="note-card-tools" onClick={e => e.stopPropagation()}>
                    <button
                        type="button"
                        className={`life-icon-btn${note.pinned ? ' is-on' : ''}`}
                        title={note.pinned ? 'Unpin note' : 'Pin note'}
                        onClick={() => onTogglePin(note)}
                    >
                        <Pin size={13} strokeWidth={2} />
                    </button>
                    <button
                        type="button"
                        className="life-icon-btn"
                        title={note.archived ? 'Restore note' : 'Archive note'}
                        onClick={() => onToggleArchive(note)}
                    >
                        {note.archived ? <ArchiveRestore size={13} /> : <Archive size={13} />}
                    </button>
                    <button type="button" className="life-icon-btn is-danger" title="Delete note" onClick={() => onDelete(note)}>
                        <Trash2 size={13} />
                    </button>
                </div>
            </div>
            <h3>{note.title}</h3>
            {note.body
                ? <p className="note-body">{note.body}</p>
                : <p className="note-body is-empty">No details yet — open to write.</p>}
            {note.tags.length > 0 && (
                <div className="note-tags">
                    {note.tags.slice(0, 4).map(t => <span key={t}>#{t}</span>)}
                </div>
            )}
            <footer>
                <span>{timeAgo(note.updatedAt)}</span>
                <span className="dot-sep">·</span>
                <span>{wordCount(note.body)} words</span>
                {note.attachments?.length > 0 && (
                    <span className="note-attach-count" title={`${note.attachments.length} attachment${note.attachments.length === 1 ? '' : 's'}`}>
                        <Paperclip size={11} /> {note.attachments.length}
                    </span>
                )}
            </footer>
        </article>
    );
}

function NoteEditor({ note, onClose, onSave, onDelete }) {
    const [cats] = useCategories('note');
    const pool = useMemo(() => categoryPool(cats, [note]), [cats, note]);
    const [draft, setDraft] = useState(() => ({ ...note, tagsText: (note.tags || []).join(', ') }));
    const isNew = !note.title;
    const originalAttachmentIds = useRef(new Set((note.attachments || []).map(a => a.id)));

    // Files attached to an abandoned draft have no record to belong to; drop
    // them when the editor closes without saving.
    const close = () => {
        (draft.attachments || []).forEach(a => {
            if (!originalAttachmentIds.current.has(a.id)) deleteAttachment(a.id).catch(() => { });
        });
        onClose();
    };

    useEffect(() => {
        const onKey = e => {
            if (e.key === 'Escape') close();
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault();
                submit();
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    });

    const submit = () => {
        const title = draft.title.trim() || 'Untitled note';
        const tags = draft.tagsText.split(',').map(t => t.trim().replace(/^#/, '')).filter(Boolean);
        onSave({ ...draft, title, tags, updatedAt: Date.now() });
    };

    return (
        <Modal
            title={isNew ? 'New note' : 'Edit note'}
            subtitle={isNew ? 'CAPTURE' : `EDITED ${formatDay(note.updatedAt).toUpperCase()}`}
            onClose={close}
            wide
            footer={(
                <>
                    <div className="life-modal-left">
                        {!isNew && (
                            <button type="button" className="life-btn is-ghost is-danger" onClick={() => onDelete(note)}>
                                <Trash2 size={14} /> Delete
                            </button>
                        )}
                    </div>
                    <button type="button" className="life-btn" onClick={close}>Cancel</button>
                    <button type="button" className="life-btn is-primary" onClick={submit}>
                        <PencilLine size={14} /> {isNew ? 'Create note' : 'Save changes'}
                    </button>
                </>
            )}
        >
            <input
                className="note-title-input"
                placeholder="Note title"
                value={draft.title}
                onChange={e => setDraft({ ...draft, title: e.target.value })}
                autoFocus={isNew}
            />
            <div className="life-field">
                <span className="life-field-label">Category</span>
                <div className="life-chip-row">
                    {pool.map(cat => (
                        <Chip
                            key={cat}
                            label={cat}
                            active={draft.category === cat}
                            onClick={() => setDraft({ ...draft, category: cat })}
                        />
                    ))}
                </div>
            </div>
            <label className="life-field">
                <span className="life-field-label"><Tag size={12} /> Tags <em>comma separated</em></span>
                <input
                    className="life-input"
                    placeholder="tax, sip, march"
                    value={draft.tagsText}
                    onChange={e => setDraft({ ...draft, tagsText: e.target.value })}
                />
            </label>
            <label className="life-field">
                <span className="life-field-label">Details</span>
                <textarea
                    className="life-textarea"
                    rows={12}
                    placeholder="Write freely — decisions, numbers, next steps…"
                    value={draft.body}
                    onChange={e => setDraft({ ...draft, body: e.target.value })}
                />
            </label>
            <AttachmentField
                kind="note"
                ownerId={draft.id}
                value={draft.attachments || []}
                onChange={attachments => setDraft(prev => ({ ...prev, attachments }))}
            />
            <button
                type="button"
                className={`note-pin-toggle${draft.pinned ? ' is-on' : ''}`}
                onClick={() => setDraft({ ...draft, pinned: !draft.pinned })}
            >
                <Pin size={13} /> {draft.pinned ? 'Pinned to the top' : 'Pin this note'}
            </button>
        </Modal>
    );
}

export default function NotesPage() {
    // Destructive actions ask through the app's own dialog, never confirm().
    const { ask, dialog } = useConfirm();
    const [notes, setNotes] = useCollection(NOTES_KEY);
    const [cats, setCats] = useCategories('note');
    const pool = useMemo(() => categoryPool(cats, notes), [cats, notes]);
    const [manageCats, setManageCats] = useState(false);
    const [query, setQuery] = useState('');
    const [category, setCategory] = useState('All');
    const [sort, setSort] = useState('updated');
    const [showArchived, setShowArchived] = useState(false);
    const [editing, setEditing] = useState(null);

    const active = useMemo(() => notes.filter(n => !!n.archived === showArchived), [notes, showArchived]);

    const counts = useMemo(() => {
        const map = { All: active.length };
        pool.forEach(c => { map[c] = active.filter(n => n.category === c).length; });
        return map;
    }, [active, cats]);

    const visible = useMemo(() => {
        let list = active;
        if (category !== 'All') list = list.filter(n => n.category === category);
        if (query.trim()) {
            const q = query.trim().toLowerCase();
            list = list.filter(n =>
                n.title.toLowerCase().includes(q) ||
                n.body.toLowerCase().includes(q) ||
                n.category.toLowerCase().includes(q) ||
                n.tags.some(t => t.toLowerCase().includes(q))
            );
        }
        const sorted = [...list].sort((a, b) => {
            if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
            if (sort === 'title') return a.title.localeCompare(b.title);
            if (sort === 'created') return b.createdAt - a.createdAt;
            return b.updatedAt - a.updatedAt;
        });
        return sorted;
    }, [active, category, query, sort]);

    const pinned = visible.filter(n => n.pinned);
    const rest = visible.filter(n => !n.pinned);

    const saveNote = draft => {
        const exists = notes.some(n => n.id === draft.id);
        setNotes(prev => exists ? prev.map(n => n.id === draft.id ? draft : n) : [draft, ...prev]);
        logActivity(exists ? `Note updated: “${draft.title}”` : `Note created: “${draft.title}”`, 'note', draft.category);
        setEditing(null);
    };

    const deleteNote = async note => {
        const ok = await ask({
            title: `Delete “${note.title}”?`,
            message: 'The note is removed for good. This cannot be undone.',
            confirmLabel: 'Delete note',
        });
        if (!ok) return;
        setNotes(prev => prev.filter(n => n.id !== note.id));
        logActivity(`Note deleted: “${note.title}”`, 'note');
        setEditing(null);
    };

    const togglePin = note => {
        setNotes(prev => prev.map(n => n.id === note.id ? { ...n, pinned: !n.pinned, updatedAt: Date.now() } : n));
    };

    const toggleArchive = note => {
        setNotes(prev => prev.map(n => n.id === note.id ? { ...n, archived: !n.archived, pinned: false, updatedAt: Date.now() } : n));
        logActivity(note.archived ? `Note restored: “${note.title}”` : `Note archived: “${note.title}”`, 'note');
    };

    const pinnedCount = notes.filter(n => n.pinned && !n.archived).length;
    const archivedCount = notes.filter(n => n.archived).length;
    const categoryCount = new Set(notes.map(n => n.category)).size;

    return (
        <div className="life-page notes-page">
            {dialog}
            <PageHero>
                <button type="button" className="life-btn is-primary" onClick={() => setEditing(emptyDraft())} aria-label="New note">
                    <Plus size={15} /><span className="life-btn-label">New note</span>
                </button>
            </PageHero>

            <div className="life-stats">
                <StatTile label="Total notes" value={notes.length} hint={`${wordCount(notes.map(n => n.body).join(' '))} words captured`} icon={NotebookPen} tint="#d97757" />
                <StatTile label="Pinned" value={pinnedCount} hint="Always in sight" icon={Pin} tint="#c9a227" />
                <StatTile label="Categories used" value={categoryCount} hint={`of ${pool.length} available`} icon={Tag} tint="#7fa650" />
                <StatTile label="Archived" value={archivedCount} hint="Kept, not in the way" icon={Archive} tint="#6a9bd0" />
            </div>

            <div className="life-toolbar">
                <div className="life-chip-row">
                    <Chip label="All" active={category === 'All'} count={counts.All} onClick={() => setCategory('All')} tint="#a89f94" />
                    {pool.map(cat => (
                        <Chip key={cat} label={cat} active={category === cat} count={counts[cat]} onClick={() => setCategory(cat)} />
                    ))}
                    <button type="button" className="life-chip is-manage" onClick={() => setManageCats(true)} title="Add, rename or delete categories">
                        <SlidersHorizontal size={13} /><span>Manage</span>
                    </button>
                </div>
                <div className="life-toolbar-right">
                    <Select
                        compact
                        className="is-sort"
                        label={showArchived ? 'Archive' : 'Sort'}
                        value={sort}
                        onChange={value => {
                            if (value === '__archive__') setShowArchived(v => !v);
                            else setSort(value);
                        }}
                        options={[
                            ...SORTS.map(s => ({ value: s.id, label: s.label })),
                            { value: '__archive__', label: showArchived ? 'Hide archive' : 'Show archive' },
                        ]}
                    />
                </div>
            </div>

            <div className="panel life-panel">
            <div className="life-scroll">
            {visible.length === 0 ? (
                <EmptyState
                    icon={showArchived ? Archive : FileText}
                    title={showArchived ? 'Nothing archived yet' : query || category !== 'All' ? 'No notes match this view' : 'Your first note is waiting'}
                    hint={showArchived
                        ? 'Notes you archive are kept here, out of the way but never lost.'
                        : query || category !== 'All'
                            ? 'Try a different category or clear the search.'
                            : 'Capture a decision, a tax idea or a reminder for future you.'}
                    action={!showArchived && !query && category === 'All' && (
                        <button type="button" className="life-btn is-primary" onClick={() => setEditing(emptyDraft())}>
                            <Plus size={14} /> Write a note
                        </button>
                    )}
                />
            ) : (
                <>
                    {pinned.length > 0 && (
                        <section className="notes-section">
                            <div className="life-section-label"><Pin size={12} /> Pinned</div>
                            <div className="notes-grid">
                                {pinned.map(note => (
                                    <NoteCard key={note.id} note={note} onOpen={setEditing}
                                        onTogglePin={togglePin} onToggleArchive={toggleArchive} onDelete={deleteNote} />
                                ))}
                            </div>
                        </section>
                    )}
                    {rest.length > 0 && (
                        <section className="notes-section">
                            {pinned.length > 0 && <div className="life-section-label"><Undo2 size={12} /> Everything else</div>}
                            <div className="notes-grid">
                                {rest.map(note => (
                                    <NoteCard key={note.id} note={note} onOpen={setEditing}
                                        onTogglePin={togglePin} onToggleArchive={toggleArchive} onDelete={deleteNote} />
                                ))}
                            </div>
                        </section>
                    )}
                </>
            )}
            </div>
            </div>

            {editing && (
                <NoteEditor
                    note={editing}
                    onClose={() => setEditing(null)}
                    onSave={saveNote}
                    onDelete={deleteNote}
                />
            )}

            <CategoryManager
                open={manageCats}
                onClose={() => setManageCats(false)}
                title="Note categories"
                categories={pool}
                onChange={setCats}
                onRename={(from, to) => setNotes(prev => prev.map(n => (n.category === from ? { ...n, category: to } : n)))}
                onDelete={cat => {
                    const fallback = pool.find(c => c !== cat) || 'Personal';
                    setNotes(prev => prev.map(n => (n.category === cat ? { ...n, category: fallback } : n)));
                    if (category === cat) setCategory('All');
                }}
            />
        </div>
    );
}
