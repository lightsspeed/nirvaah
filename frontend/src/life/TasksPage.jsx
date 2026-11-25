import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    Plus, Check, Trash2, Pencil, ListChecks, Flame, CalendarClock,
    CircleCheckBig, ChevronDown, CalendarDays, Flag, StickyNote, X, SlidersHorizontal,
    Paperclip,
} from 'lucide-react';
import {
    useCollection, logActivity, todayISO, shiftISO, shortDay, timeAgo, uid,
    isOverdue, monthKey, TASKS_KEY, PRIORITIES, priorityMeta, tintOf, categoryPool, useCategories,
} from './store';
import { PageHero, StatTile, Chip, Segmented, EmptyState, Progress, CategoryManager, Select } from './ui';
import AttachmentField from './AttachmentField';
import { deleteAttachment } from './attachments';
import { useConfirm } from '../ConfirmDialog';
import { parseDateOnly } from '../dates';

const VIEWS = [
    { id: 'open', label: 'Open' },
    { id: 'today', label: 'Today' },
    { id: 'upcoming', label: 'Upcoming' },
    { id: 'done', label: 'Done' },
    { id: 'all', label: 'All' },
];

const SORTS = [
    { id: 'due', label: 'Due date' },
    { id: 'priority', label: 'Priority' },
    { id: 'created', label: 'Newest' },
];

const buckets = [
    { id: 'overdue', label: 'Overdue', tint: '#d97757' },
    { id: 'today', label: 'Today', tint: '#c9a227' },
    { id: 'upcoming', label: 'Upcoming', tint: '#6a9bd0' },
    { id: 'undated', label: 'No date', tint: '#a89f94' },
    { id: 'done', label: 'Completed', tint: '#7fa650' },
];

function TaskRow({ task, onToggle, onDelete, onSave, hideCategory = false }) {
    const [cats] = useCategories('task');
    const pool = useMemo(() => categoryPool(cats, [task]), [cats, task]);
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(task);
    const originalAttachmentIds = useRef(new Set((task.attachments || []).map(a => a.id)));
    const prio = priorityMeta(task.priority);
    const overdue = !task.done && isOverdue(task.due);

    useEffect(() => {
        setDraft(task);
        originalAttachmentIds.current = new Set((task.attachments || []).map(a => a.id));
    }, [task]);

    // Cancelling an edit abandons files added in it; they have no other owner.
    const cancelEdit = () => {
        (draft.attachments || []).forEach(a => {
            if (!originalAttachmentIds.current.has(a.id)) deleteAttachment(a.id).catch(() => { });
        });
        setEditing(false);
    };

    if (editing) {
        return (
            <div className="task-row is-editing">
                <div className="task-edit">
                    <input
                        className="life-input"
                        value={draft.text}
                        onChange={e => setDraft({ ...draft, text: e.target.value })}
                        onKeyDown={e => {
                            if (e.key === 'Enter') { onSave(draft); setEditing(false); }
                            if (e.key === 'Escape') cancelEdit();
                        }}
                        autoFocus
                    />
                    <textarea
                        className="life-textarea"
                        rows={2}
                        placeholder="Notes (optional)"
                        value={draft.notes}
                        onChange={e => setDraft({ ...draft, notes: e.target.value })}
                    />
                    <AttachmentField
                        kind="task"
                        ownerId={task.id}
                        value={draft.attachments || []}
                        onChange={attachments => setDraft(prev => ({ ...prev, attachments }))}
                        label="Files"
                    />
                    <div className="task-edit-grid">
                        <Select
                            label="Category"
                            value={draft.category}
                            onChange={value => setDraft({ ...draft, category: value })}
                            options={pool}
                        />
                        <Select
                            label="Priority"
                            value={draft.priority}
                            onChange={value => setDraft({ ...draft, priority: value })}
                            options={PRIORITIES.map(p => ({ value: p.id, label: p.label }))}
                        />
                        <label className="life-select">
                            <span>Due date</span>
                            <input type="date" value={draft.due || ''} onChange={e => setDraft({ ...draft, due: e.target.value })} />
                        </label>
                    </div>
                    <div className="task-edit-actions">
                        <button type="button" className="life-btn is-ghost" onClick={cancelEdit}>Cancel</button>
                        <button type="button" className="life-btn is-primary" onClick={() => { onSave(draft); setEditing(false); }}>
                            <Check size={14} /> Save
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className={`task-row${task.done ? ' is-done' : ''}`}>
            <button
                type="button"
                className={`task-check${task.done ? ' is-checked' : ''}`}
                onClick={() => onToggle(task)}
                aria-label={task.done ? 'Mark as not done' : 'Mark as done'}
            >
                {task.done && <Check size={12} strokeWidth={3} />}
            </button>
            {task.due && (() => {
                const day = parseDateOnly(task.due);
                return (
                    <span
                        className={`journal-day${overdue ? ' is-overdue' : ''}`}
                        style={{ '--chip': overdue ? '#d9534f' : tintOf(task.category) }}
                        title={shortDay(task.due)}
                    >
                        <b>{day ? day.getDate() : '—'}</b>
                        <small>{day ? day.toLocaleDateString('en-IN', { month: 'short' }) : ''}</small>
                    </span>
                );
            })()}
            <div className="task-main" onClick={() => setEditing(true)} role="button" tabIndex={0}
                onKeyDown={e => { if (e.key === 'Enter') setEditing(true); }}>
                <span className="task-text">{task.text}</span>
                <div className="task-meta">
                    {!hideCategory && (
                        <span className="task-cat" style={{ '--chip': tintOf(task.category) }}>
                            <i />{task.category}
                        </span>
                    )}
                    {overdue && <span className="task-due is-overdue">overdue</span>}
                    {task.notes && <span className="task-note-dot" title={task.notes}><StickyNote size={11} /></span>}
                    {task.attachments?.length > 0 && (
                        <span className="task-note-dot" title={`${task.attachments.length} attachment${task.attachments.length === 1 ? '' : 's'}`}>
                            <Paperclip size={11} /> {task.attachments.length}
                        </span>
                    )}
                    <span className="task-age">{timeAgo(task.createdAt)}</span>
                </div>
            </div>
            <span className="task-prio" style={{ '--chip': prio.tint }} title={`${prio.label} priority`}>
                <Flag size={11} /> {prio.label}
            </span>
            <div className="task-actions">
                <button type="button" className="life-icon-btn" title="Edit task" onClick={() => setEditing(true)}>
                    <Pencil size={13} />
                </button>
                <button type="button" className="life-icon-btn is-danger" title="Delete task" onClick={() => onDelete(task)}>
                    <Trash2 size={13} />
                </button>
            </div>
        </div>
    );
}

const PROJECT_VIEWS = [
    { id: 'all', label: 'All' },
    { id: 'active', label: 'Active' },
    { id: 'done', label: 'Done' },
    { id: 'overdue', label: 'Overdue' },
    { id: 'soon', label: 'Next 7 days' },
];

const PROJECT_SORTS = [
    { id: 'manual', label: 'Manual' },
    { id: 'due', label: 'Due date' },
    { id: 'priority', label: 'Priority' },
];

/* A category, opened as a project: progress, quick add, filters and sort.
   Same rows as the main list — only the frame around them changes. */
function ProjectPanel({
    name, rows, counts, total, view, onView, sort, onSort,
    onAdd, onToggle, onSave, onDelete, onDeleteProject, progress,
}) {
    const [text, setText] = useState('');
    const [confirming, setConfirming] = useState(false);

    const submit = e => {
        e.preventDefault();
        const value = text.trim();
        if (!value) return;
        onAdd(value);
        setText('');
    };

    return (
        <section className="project-panel">
            <header className="project-head">
                <div className="project-head-main">
                    <div className="project-progress">
                        <Progress value={progress} />
                        <span><b>{counts.done}</b> / {total} done</span>
                    </div>
                </div>
                <div className="project-head-actions">
                    {confirming ? (
                        <>
                            <span className="project-confirm-text">Delete {total} task{total === 1 ? '' : 's'}?</span>
                            <button type="button" className="life-btn is-ghost" onClick={() => setConfirming(false)}>Cancel</button>
                            <button type="button" className="life-btn is-danger" onClick={onDeleteProject}>Delete</button>
                        </>
                    ) : (
                        <button type="button" className="link is-quiet" onClick={() => setConfirming(true)}>Delete project</button>
                    )}
                </div>
            </header>

            <form className="project-quickadd" onSubmit={submit}>
                <input
                    className="life-input"
                    placeholder="Add a task"
                    value={text}
                    onChange={e => setText(e.target.value)}
                />
                <button type="submit" className="life-btn is-primary" disabled={!text.trim()}>
                    <Plus size={14} /> Add
                </button>
            </form>

            <div className="project-toolbar">
                <Segmented
                    options={PROJECT_VIEWS.map(v => ({ ...v, count: counts[v.id] }))}
                    value={view}
                    onChange={onView}
                />
                <Select
                    compact
                    className="is-sort"
                    label="Order"
                    value={sort}
                    onChange={onSort}
                    options={PROJECT_SORTS.map(s => ({ value: s.id, label: s.label }))}
                />
            </div>

            {rows.length === 0 ? (
                <EmptyState
                    icon={ListChecks}
                    title={view === 'done' ? 'Nothing completed yet' : 'Nothing here right now'}
                    hint={view === 'done' ? 'Finished tasks land here.' : 'Add the next action above — it appears instantly.'}
                />
            ) : (
                <div className="task-list project-list">
                    {rows.map(task => (
                        <TaskRow
                            key={task.id}
                            task={task}
                            hideCategory
                            onToggle={onToggle}
                            onDelete={onDelete}
                            onSave={onSave}
                        />
                    ))}
                </div>
            )}
        </section>
    );
}

export default function TasksPage() {
    // Destructive actions ask through the app's own dialog, never confirm().
    const { ask, dialog } = useConfirm();
    const [tasks, setTasks] = useCollection(TASKS_KEY);
    const [view, setView] = useState('open');
    const [category, setCategory] = useState('All');
    const [query, setQuery] = useState('');
    const [sort, setSort] = useState('due');
    const [cats, setCats] = useCategories('task');
    const pool = useMemo(() => categoryPool(cats, tasks), [cats, tasks]);
    const [draft, setDraft] = useState({ id: '', text: '', category: 'Bills', priority: 'medium', due: '', notes: '', attachments: [] });
    const [adding, setAdding] = useState(false);
    const [manageCats, setManageCats] = useState(false);
    // Project view: a category opened as its own workspace.
    const [projectView, setProjectView] = useState('all');
    const [projectSort, setProjectSort] = useState('manual');
    const [quickAdd, setQuickAdd] = useState('');

    const t = todayISO();
    const weekAhead = shiftISO(t, 7);

    const stats = useMemo(() => {
        const open = tasks.filter(x => !x.done);
        const thisMonth = monthKey(Date.now());
        return {
            open: open.length,
            overdue: open.filter(x => isOverdue(x.due)).length,
            today: open.filter(x => x.due === t).length,
            doneWeek: tasks.filter(x => x.done && x.completedAt && x.completedAt > Date.now() - 7 * 864e5).length,
            total: tasks.length,
        };
    }, [tasks, t]);

    const counts = useMemo(() => ({
        open: tasks.filter(x => !x.done).length,
        today: tasks.filter(x => !x.done && (x.due === t || isOverdue(x.due))).length,
        upcoming: tasks.filter(x => !x.done && x.due && x.due > t).length,
        done: tasks.filter(x => x.done).length,
        all: tasks.length,
    }), [tasks, t]);

    const catCounts = useMemo(() => {
        const map = { All: tasks.filter(x => !x.done).length };
        pool.forEach(c => { map[c] = tasks.filter(x => !x.done && x.category === c).length; });
        return map;
    }, [tasks, cats]);

    const visible = useMemo(() => {
        let list = tasks;
        if (view === 'open') list = list.filter(x => !x.done);
        else if (view === 'today') list = list.filter(x => !x.done && (x.due === t || isOverdue(x.due)));
        else if (view === 'upcoming') list = list.filter(x => !x.done && x.due && x.due > t);
        else if (view === 'done') list = list.filter(x => x.done);

        if (category !== 'All') list = list.filter(x => x.category === category);
        if (query.trim()) {
            const q = query.trim().toLowerCase();
            list = list.filter(x => x.text.toLowerCase().includes(q) || (x.notes || '').toLowerCase().includes(q));
        }
        const prioRank = id => priorityMeta(id).rank;
        return [...list].sort((a, b) => {
            if (a.done !== b.done) return a.done ? 1 : -1;
            if (sort === 'priority') return prioRank(a.priority) - prioRank(b.priority) || (a.due || 'z').localeCompare(b.due || 'z');
            if (sort === 'created') return b.createdAt - a.createdAt;
            const ad = a.due || '9999-12-31';
            const bd = b.due || '9999-12-31';
            return ad.localeCompare(bd) || prioRank(a.priority) - prioRank(b.priority);
        });
    }, [tasks, view, category, query, sort, t]);

    const grouped = useMemo(() => {
        const g = { overdue: [], today: [], upcoming: [], undated: [], done: [] };
        visible.forEach(x => {
            if (x.done) g.done.push(x);
            else if (!x.due) g.undated.push(x);
            else if (isOverdue(x.due)) g.overdue.push(x);
            else if (x.due === t) g.today.push(x);
            else g.upcoming.push(x);
        });
        return g;
    }, [visible, t]);

    const showGroups = view === 'all' || view === 'open';

    const addTask = e => {
        e.preventDefault();
        const text = draft.text.trim();
        if (!text) return;
        const task = {
            id: draft.id || uid(),
            text,
            notes: draft.notes.trim(),
            attachments: draft.attachments || [],
            done: false,
            priority: draft.priority,
            category: draft.category,
            due: draft.due,
            createdAt: Date.now(),
            completedAt: null,
        };
        setTasks(prev => [task, ...prev]);
        logActivity(`Task added: “${text}”`, 'task', task.category);
        // A fresh id keeps the open composer ready for its next task (and its files).
        setDraft({ ...draft, id: uid(), text: '', notes: '', due: '', attachments: [] });
    };

    // Leaving the page with the composer open must not leave unattached files.
    const composerFiles = useRef([]);
    useEffect(() => { composerFiles.current = draft.attachments || []; }, [draft.attachments]);
    useEffect(() => () => {
        composerFiles.current.forEach(a => deleteAttachment(a.id).catch(() => { }));
    }, []);

    const openComposer = () => {
        if (adding) {
            // Closing the composer abandons everything typed in it, including
            // any file uploaded for a task that will never exist.
            (draft.attachments || []).forEach(a => deleteAttachment(a.id).catch(() => { }));
            setDraft(prev => ({ ...prev, id: '', text: '', notes: '', due: '', attachments: [] }));
            setAdding(false);
            return;
        }
        setDraft(prev => ({ ...prev, id: uid(), attachments: [] }));
        setAdding(true);
    };

    const toggle = task => {
        setTasks(prev => prev.map(x => x.id === task.id
            ? { ...x, done: !x.done, completedAt: !x.done ? Date.now() : null }
            : x));
        logActivity(task.done ? `Task reopened: “${task.text}”` : `Task completed: “${task.text}”`, 'task');
    };

    const save = next => {
        setTasks(prev => prev.map(x => x.id === next.id ? next : x));
        logActivity(`Task updated: “${next.text}”`, 'task');
    };

    const remove = async task => {
        const ok = await ask({
            title: `Delete “${task.text}”?`,
            message: 'The task and its completion state are removed. This cannot be undone.',
            confirmLabel: 'Delete task',
        });
        if (!ok) return;
        setTasks(prev => prev.filter(x => x.id !== task.id));
        logActivity(`Task deleted: “${task.text}”`, 'task');
    };

    const clearDone = async () => {
        const count = tasks.filter(x => x.done).length;
        if (!count) return;
        const ok = await ask({
            title: `Clear ${count} completed task${count === 1 ? '' : 's'}?`,
            message: 'Only finished tasks are removed. Open tasks stay where they are.',
            confirmLabel: 'Clear completed',
        });
        if (!ok) return;
        setTasks(prev => prev.filter(x => !x.done));
        logActivity(`Cleared ${count} completed task${count === 1 ? '' : 's'}`, 'task');
    };

    const isProject = category !== 'All';

    const projectTasks = useMemo(() => {
        if (!isProject) return [];
        let list = tasks.filter(x => x.category === category);
        if (query.trim()) {
            const q = query.trim().toLowerCase();
            list = list.filter(x => x.text.toLowerCase().includes(q) || (x.notes || '').toLowerCase().includes(q));
        }
        const prioRank = id => priorityMeta(id).rank;
        if (projectSort === 'priority') {
            list = [...list].sort((a, b) => prioRank(a.priority) - prioRank(b.priority));
        } else if (projectSort === 'due') {
            list = [...list].sort((a, b) => (a.due || '9999-12-31').localeCompare(b.due || '9999-12-31'));
        }
        return list;
    }, [tasks, category, isProject, projectSort, query]);

    const projectCounts = useMemo(() => {
        const all = tasks.filter(x => x.category === category);
        const open = all.filter(x => !x.done);
        return {
            all: all.length,
            active: open.length,
            done: all.length - open.length,
            overdue: open.filter(x => isOverdue(x.due)).length,
            soon: open.filter(x => x.due && x.due >= t && x.due <= weekAhead).length,
        };
    }, [tasks, category, t, weekAhead]);

    const projectRows = useMemo(() => projectTasks.filter(x => {
        if (projectView === 'active') return !x.done;
        if (projectView === 'done') return x.done;
        if (projectView === 'overdue') return !x.done && isOverdue(x.due);
        if (projectView === 'soon') return !x.done && x.due && x.due >= t && x.due <= weekAhead;
        return true;
    }), [projectTasks, projectView, t, weekAhead]);

    const projectProgress = projectCounts.all
        ? Math.round((projectCounts.done / projectCounts.all) * 100)
        : 0;

    const addToProject = text => {
        const task = {
            id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
            text,
            notes: '',
            done: false,
            priority: 'medium',
            category,
            due: '',
            createdAt: Date.now(),
            completedAt: null,
        };
        setTasks(prev => [task, ...prev]);
        logActivity(`Task added: “${text}”`, 'task', category);
    };

    const deleteProject = async () => {
        const doomed = tasks.filter(x => x.category === category);
        const ok = await ask({
            title: `Delete the “${category}” project?`,
            message: `${doomed.length} task${doomed.length === 1 ? '' : 's'} and the category itself are removed for good. This cannot be undone.`,
            confirmLabel: 'Delete project',
        });
        if (!ok) return;
        setTasks(prev => prev.filter(x => x.category !== category));
        setCats(prev => prev.filter(c => c !== category));
        logActivity(`Project deleted: ${category} (${doomed.length} task${doomed.length === 1 ? '' : 's'})`, 'task');
        setCategory('All');
    };

    const progress = stats.total ? Math.round(((stats.total - stats.open) / stats.total) * 100) : 0;
    const dueThisWeek = tasks.filter(x => !x.done && x.due && x.due >= t && x.due <= weekAhead).length;

    const categoryChips = (
        <div className="life-chip-row">
            <Chip label="All" active={category === 'All'} count={catCounts.All} onClick={() => setCategory('All')} tint="#a89f94" />
            {pool.map(c => (
                <Chip key={c} label={c} active={category === c} count={catCounts[c]} onClick={() => setCategory(c)} />
            ))}
        </div>
    );

    const manageCategories = (
        <button type="button" className="life-chip is-manage" onClick={() => setManageCats(true)} title="Add, rename or delete categories">
            <SlidersHorizontal size={13} /><span>Manage</span>
        </button>
    );

    return (
        <div className="life-page tasks-page">
            {dialog}
            <PageHero
                title={isProject ? category : undefined}
                description={isProject
                    ? `${projectCounts.done} of ${projectCounts.all} done · ${projectCounts.active} open`
                    : undefined}
            >
                {!isProject && (
                    <button
                        type="button"
                        className="life-btn is-primary"
                        onClick={openComposer}
                        aria-label={adding ? 'Close task composer' : 'New task'}
                    >
                        {adding ? <X size={15} /> : <Plus size={15} />}
                        <span className="life-btn-label">{adding ? 'Close' : 'New task'}</span>
                    </button>
                )}
            </PageHero>

            {!isProject && <div className="life-stats">
                <StatTile label="Open" value={stats.open} hint={`${dueThisWeek} due in the next 7 days`} icon={ListChecks} tint="#6a9bd0" />
                <StatTile label="Overdue" value={stats.overdue} hint={stats.overdue ? 'Needs attention first' : 'All clear'} icon={Flame} tint="#d97757" />
                <StatTile label="Due today" value={stats.today} hint="Keep the list honest" icon={CalendarClock} tint="#c9a227" />
                <StatTile label="Done this week" value={stats.doneWeek} hint={`${progress}% of all tasks closed`} icon={CircleCheckBig} tint="#7fa650" />
            </div>}

            {!isProject && adding && (
                <form className="task-composer" onSubmit={addTask}>
                    <div className="task-composer-main">
                        <input
                            className="life-input"
                            placeholder="What needs doing? e.g. Pay HDFC card bill"
                            value={draft.text}
                            onChange={e => setDraft({ ...draft, text: e.target.value })}
                            autoFocus
                        />
                        <button type="submit" className="life-btn is-primary"><Plus size={14} /> Add</button>
                    </div>
                    <div className="task-composer-grid">
                        <Select
                            label="Category"
                            value={draft.category}
                            onChange={value => setDraft({ ...draft, category: value })}
                            options={pool}
                        />
                        <Select
                            label="Priority"
                            value={draft.priority}
                            onChange={value => setDraft({ ...draft, priority: value })}
                            options={PRIORITIES.map(p => ({ value: p.id, label: p.label }))}
                        />
                        <label className="life-select">
                            <span>Due date</span>
                            <input type="date" value={draft.due} onChange={e => setDraft({ ...draft, due: e.target.value })} />
                        </label>
                        <label className="life-select is-grow">
                            <span>Note</span>
                            <input placeholder="Optional context" value={draft.notes} onChange={e => setDraft({ ...draft, notes: e.target.value })} />
                        </label>
                    </div>
                    <AttachmentField
                        kind="task"
                        ownerId={draft.id}
                        value={draft.attachments || []}
                        onChange={attachments => setDraft(prev => ({ ...prev, attachments }))}
                        label="Files"
                    />
                </form>
            )}

            {!isProject && <div className="life-toolbar">
                <Segmented
                    options={VIEWS.map(v => ({ ...v, count: counts[v.id] }))}
                    value={view}
                    onChange={setView}
                />
                {categoryChips}
                {manageCategories}
                <div className="life-toolbar-right">
                    <Select
                        compact
                        className="is-sort"
                        label="Sort"
                        value={sort}
                        onChange={setSort}
                        options={SORTS.map(s => ({ value: s.id, label: s.label }))}
                    />
                </div>
            </div>}

            <div className="task-progress-row">
                {isProject && (
                    <>
                        {categoryChips}
                        {manageCategories}
                    </>
                )}
                {!isProject && (
                    <div className="task-progress">
                        <span>{stats.total - stats.open} of {stats.total} done</span>
                        <Progress value={progress} />
                    </div>
                )}
            </div>

            <div className="panel life-panel">
            <div className="life-scroll">
            {isProject ? (
                <ProjectPanel
                    name={category}
                    rows={projectRows}
                    counts={projectCounts}
                    total={projectCounts.all}
                    view={projectView}
                    onView={setProjectView}
                    sort={projectSort}
                    onSort={setProjectSort}
                    onAdd={addToProject}
                    onToggle={toggle}
                    onSave={save}
                    onDelete={remove}
                    onDeleteProject={deleteProject}
                    progress={projectProgress}
                />
            ) : visible.length === 0 ? (
                <EmptyState
                    icon={ListChecks}
                    title={view === 'done' ? 'Nothing completed yet' : query ? 'No tasks match' : 'Clear list, clear head'}
                    hint={view === 'done' ? 'Finished tasks land here.' : query ? 'Try another word or category.' : 'Add the smallest next action — the rest follows.'}
                    action={!query && (
                        <button type="button" className="life-btn is-primary" onClick={() => setAdding(true)}>
                            <Plus size={14} /> Add a task
                        </button>
                    )}
                />
            ) : (
                <div className="task-list">
                    {showGroups ? buckets.map(bucket => {
                        const rows = grouped[bucket.id];
                        if (!rows.length) return null;
                        return (
                            <section key={bucket.id} className="task-group">
                                <div className="task-group-head" style={{ '--group': bucket.tint }}>
                                    <span><i />{bucket.label}</span>
                                    <b>{rows.length}</b>
                                </div>
                                {rows.map(task => (
                                    <TaskRow key={task.id} task={task} onToggle={toggle} onDelete={remove} onSave={save} />
                                ))}
                            </section>
                        );
                    }) : (
                        <section className="task-group">
                            <div className="task-group-head" style={{ '--group': '#a89f94' }}>
                                <span><i />{VIEWS.find(v => v.id === view)?.label}</span>
                                <b>{visible.length}</b>
                            </div>
                            {visible.map(task => (
                                <TaskRow key={task.id} task={task} onToggle={toggle} onDelete={remove} onSave={save} />
                            ))}
                        </section>
                    )}
                    {counts.done > 0 && view !== 'done' && (
                        <button type="button" className="task-clear" onClick={clearDone}>
                            <X size={13} /> Clear {counts.done} completed
                        </button>
                    )}
                </div>
            )}
            </div>
            </div>

            <CategoryManager
                open={manageCats}
                onClose={() => setManageCats(false)}
                title="Task categories"
                categories={pool}
                onChange={setCats}
                onRename={(from, to) => setTasks(prev => prev.map(x => (x.category === from ? { ...x, category: to } : x)))}
                onDelete={cat => {
                    const fallback = pool.find(c => c !== cat) || 'Personal';
                    setTasks(prev => prev.map(x => (x.category === cat ? { ...x, category: fallback } : x)));
                    if (category === cat) setCategory('All');
                    if (draft.category === cat) setDraft(d => ({ ...d, category: fallback }));
                }}
            />
        </div>
    );
}
