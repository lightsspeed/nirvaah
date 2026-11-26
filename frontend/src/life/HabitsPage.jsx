import React, { useMemo, useState } from 'react';
import {
    Plus, Check, Flame, CalendarCheck, Trash2, Pencil, ListChecks, LayoutDashboard,
} from 'lucide-react';
import {
    useCollection, logActivity, uid, todayISO, shiftISO, HABITS_KEY,
    formatDay,
} from './store';
import { PageHero, StatTile, Chip, EmptyState, Modal, Progress } from './ui';
import CustomSelect from '../CustomSelect';
import { useConfirm } from '../ConfirmDialog';
import { parseDateOnly } from '../dates';

const CATEGORIES = ['Health', 'Mind', 'Money', 'Work', 'Home', 'Personal'];
const WEEKDAYS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

const blankHabit = () => ({
    id: uid(),
    name: '',
    category: 'Health',
    target: 7,
    checks: [],
    createdAt: Date.now(),
    updatedAt: Date.now(),
});

function weekDates() {
    const today = todayISO();
    const day = parseDateOnly(today);
    const offset = day ? (day.getDay() + 6) % 7 : 0;
    const start = shiftISO(today, -offset);
    return Array.from({ length: 7 }, (_, index) => shiftISO(start, index));
}

// Every habit gets its own colour, assigned automatically from its stable id.
// A 32-bit FNV-1a hash picks a hue, saturation and lightness, so the palette is
// effectively unlimited (360 hues × 29 saturations × 16 lightness steps) and the
// colour survives reloads and stays the same on every synced device.
function habitColor(habit) {
    const key = String(habit?.id || habit?.name || '');
    let hash = 2166136261;
    for (let i = 0; i < key.length; i++) {
        hash ^= key.charCodeAt(i);
        hash = Math.imul(hash, 16777619);
    }
    hash >>>= 0;
    const hue = hash % 360;
    const saturation = 52 + ((hash >>> 8) % 29);   // 52–80%
    const lightness = 45 + ((hash >>> 16) % 16);    // 45–60%
    return `hsl(${hue} ${saturation}% ${lightness}%)`;
}

function streakOf(checks) {
    const days = new Set(checks || []);
    // A habit that has not been ticked yet today is not a broken streak.
    let cursor = days.has(todayISO()) ? todayISO() : shiftISO(todayISO(), -1);
    let streak = 0;
    while (days.has(cursor)) {
        streak += 1;
        cursor = shiftISO(cursor, -1);
    }
    return streak;
}

function yearInfo() {
    const today = todayISO();
    const day = parseDateOnly(today);
    const year = day ? day.getFullYear() : new Date().getFullYear();
    const start = `${year}-01-01`;
    const end = `${year}-12-31`;
    const days = [];
    let cursor = start;
    while (cursor <= end) {
        days.push(cursor);
        cursor = shiftISO(cursor, 1);
    }
    const first = parseDateOnly(start);
    const gridStart = shiftISO(start, -((first.getDay() + 6) % 7));
    const weeks = [];
    let weekStart = gridStart;
    while (weekStart <= end) {
        weeks.push(Array.from({ length: 7 }, (_, index) => shiftISO(weekStart, index)));
        weekStart = shiftISO(weekStart, 7);
    }
    return { year, days, elapsed: days.filter(value => value <= today), weeks, today };
}

function longestRun(checks, days) {
    const set = new Set(checks || []);
    let best = 0;
    let run = 0;
    days.forEach(day => {
        if (set.has(day)) {
            run += 1;
            best = Math.max(best, run);
        } else {
            run = 0;
        }
    });
    return best;
}

function yearStats(habits, info) {
    const elapsed = new Set(info.elapsed);
    const countFor = day => habits.filter(habit => habit.checks.includes(day)).length;
    const checkIns = habits.reduce(
        (sum, habit) => sum + habit.checks.filter(day => elapsed.has(day)).length,
        0,
    );
    const possible = habits.length * info.elapsed.length;
    const perfect = info.elapsed.filter(
        day => habits.length > 0 && countFor(day) === habits.length,
    ).length;
    const activeDays = info.elapsed.filter(day => countFor(day) > 0).length;
    const best = habits.reduce(
        (longest, habit) => Math.max(longest, longestRun(habit.checks, info.elapsed)),
        0,
    );
    const byHabit = {};
    habits.forEach(habit => {
        const count = habit.checks.filter(day => elapsed.has(day)).length;
        byHabit[habit.id] = {
            count,
            pct: info.elapsed.length ? Math.round((count / info.elapsed.length) * 100) : 0,
        };
    });
    return {
        countFor,
        checkIns,
        possible,
        pct: possible ? Math.round((checkIns / possible) * 100) : 0,
        perfect,
        activeDays,
        best,
        byHabit,
    };
}

function HabitDashboard({ habits }) {
    const info = yearInfo();
    const data = yearStats(habits, info);

    if (habits.length === 0) {
        return (
            <div className="panel life-panel">
                <EmptyState
                    icon={ListChecks}
                    title="Nothing to chart yet"
                    hint="Add a habit and start checking it off — the year fills in from your history."
                />
            </div>
        );
    }

    return (
        <div className="habit-dash">
            <div className="life-stats">
                <StatTile
                    label="Completion"
                    value={`${data.pct}%`}
                    hint={`${data.checkIns} of ${data.possible} check-ins`}
                    icon={Check}
                    tint="#7fa650"
                />
                <StatTile
                    label="Check-ins"
                    value={data.checkIns}
                    hint={`${data.activeDays} active day${data.activeDays === 1 ? '' : 's'}`}
                    icon={CalendarCheck}
                    tint="#6a9bd0"
                />
                <StatTile
                    label="Perfect days"
                    value={data.perfect}
                    hint="Every habit done"
                    icon={ListChecks}
                    tint="#c9a227"
                />
                <StatTile
                    label="Best streak"
                    value={`${data.best}d`}
                    hint="Longest run this year"
                    icon={Flame}
                    tint="#d97757"
                />
            </div>

            <div className="panel life-panel habit-year-panel">
                <div className="habit-year-head">
                    <h3>Habit heatmaps <span>· {info.year}</span></h3>
                    <small>Each square is a day</small>
                </div>
                <div className="habit-year-list">
                    {habits.map(habit => {
                        const row = data.byHabit[habit.id];
                        return (
                            <div className="habit-year-row" key={habit.id} style={{ '--habit-tint': habitColor(habit) }}>
                                <div className="habit-year-info">
                                    <span className="habit-dot" />
                                    <div className="habit-year-name">
                                        <b>{habit.name}</b>
                                        <small>{habit.category} · {row.count}/{info.elapsed.length} days · {row.pct}%</small>
                                    </div>
                                </div>
                                <div
                                    className="habit-year-map"
                                    role="img"
                                    aria-label={`${habit.name} heatmap for ${info.year}`}
                                >
                                    <div className="habit-year-weeks">
                                        {info.weeks.map((week, weekIndex) => (
                                            <div className="habit-year-week" key={`${habit.id}-${weekIndex}`}>
                                                {week.map(day => {
                                                    const outside = day < `${info.year}-01-01` || day > `${info.year}-12-31`;
                                                    const future = day > info.today;
                                                    const checked = !outside && habit.checks.includes(day);
                                                    return (
                                                        <i
                                                            key={day}
                                                            className={`habit-year-cell${outside ? ' is-outside' : ''}${future && !outside ? ' is-future' : ''}${checked ? ' is-checked' : ''}`}
                                                            title={outside ? '' : `${formatDay(day)}${checked ? ' — done' : ''}`}
                                                        />
                                                    );
                                                })}
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}

function HabitEditor({ habit, onClose, onSave, onDelete }) {
    const [draft, setDraft] = useState(habit);
    const isNew = !habit.name;

    const submit = event => {
        event.preventDefault();
        const name = draft.name.trim();
        if (!name) return;
        onSave({ ...draft, name, updatedAt: Date.now() });
    };

    return (
        <Modal
            title={isNew ? 'New habit' : 'Edit habit'}
            subtitle={isNew ? 'A SMALL ROUTINE' : `${draft.checks.length} DAYS LOGGED`}
            onClose={onClose}
            footer={(
                <>
                    <div className="life-modal-left">
                        {!isNew && (
                            <button type="button" className="life-btn is-ghost is-danger" onClick={() => onDelete(habit)}>
                                <Trash2 size={14} /> Delete
                            </button>
                        )}
                    </div>
                    <button type="button" className="life-btn" onClick={onClose}>Cancel</button>
                    <button type="button" className="life-btn is-primary" onClick={submit}>
                        <Check size={14} /> {isNew ? 'Create habit' : 'Save habit'}
                    </button>
                </>
            )}
        >
            <form className="habit-form" onSubmit={submit}>
                <label className="life-field">
                    <span className="life-field-label">Habit</span>
                    <input
                        className="life-input"
                        placeholder="e.g. Walk 30 minutes"
                        value={draft.name}
                        onChange={e => setDraft({ ...draft, name: e.target.value })}
                        autoFocus={isNew}
                    />
                </label>
                <div className="life-field">
                    <span className="life-field-label">Category</span>
                    <div className="life-chip-row">
                        {CATEGORIES.map(category => (
                            <Chip
                                key={category}
                                label={category}
                                active={draft.category === category}
                                onClick={() => setDraft({ ...draft, category })}
                            />
                        ))}
                    </div>
                </div>
                <div className="life-field">
                    <span className="life-field-label">Days per week</span>
                    <CustomSelect
                        value={draft.target}
                        onChange={value => setDraft({ ...draft, target: Number(value) })}
                        options={[1, 2, 3, 4, 5, 6, 7].map(days => ({
                            value: days,
                            label: `${days} day${days === 1 ? '' : 's'} a week`,
                        }))}
                        fullWidth
                    />
                </div>
            </form>
        </Modal>
    );
}

export default function HabitsPage() {
    const { ask, dialog } = useConfirm();
    const [habits, setHabits] = useCollection(HABITS_KEY);
    const [editing, setEditing] = useState(null);
    const [view, setView] = useState('habits');
    // Computed per render so an app left open across midnight shows the new day.
    const week = weekDates();

    const doneByHabit = useMemo(() => {
        const map = {};
        habits.forEach(habit => {
            map[habit.id] = week.filter(day => habit.checks.includes(day)).length;
        });
        return map;
    }, [habits, week]);

    const stats = useMemo(() => {
        const doneToday = habits.filter(habit => habit.checks.includes(todayISO())).length;
        const bestStreak = habits.reduce((best, habit) => Math.max(best, streakOf(habit.checks)), 0);
        const doneWeek = habits.reduce((sum, habit) => sum + (doneByHabit[habit.id] || 0), 0);
        const possible = habits.length * 7;
        return {
            active: habits.length,
            doneToday,
            bestStreak,
            weekPct: possible ? Math.round((doneWeek / possible) * 100) : 0,
            doneWeek,
        };
    }, [habits, doneByHabit]);

    const toggleDay = (habit, day) => {
        const done = habit.checks.includes(day);
        setHabits(prev => prev.map(item => {
            if (item.id !== habit.id) return item;
            const checks = done
                ? item.checks.filter(value => value !== day)
                : [...item.checks, day].sort();
            return { ...item, checks, updatedAt: Date.now() };
        }));
        logActivity(
            `${done ? 'Unchecked' : 'Checked'} ${habit.name} for ${day}`,
            'habit',
            habit.category,
        );
    };

    const saveHabit = draft => {
        const exists = habits.some(habit => habit.id === draft.id);
        setHabits(prev => exists
            ? prev.map(habit => (habit.id === draft.id ? draft : habit))
            : [...prev, draft]);
        logActivity(exists ? `Habit updated: “${draft.name}”` : `Habit created: “${draft.name}”`, 'habit', draft.category);
        setEditing(null);
    };

    const deleteHabit = async habit => {
        const ok = await ask({
            title: `Delete “${habit.name}”?`,
            message: 'The habit and its check-in history are removed for good. This cannot be undone.',
            confirmLabel: 'Delete habit',
        });
        if (!ok) return;
        setHabits(prev => prev.filter(item => item.id !== habit.id));
        logActivity(`Habit deleted: “${habit.name}”`, 'habit');
        setEditing(null);
    };

    return (
        <div className="life-page habits-page">
            {dialog}
            <PageHero actionsInHeader>
                <button
                    type="button"
                    className="life-btn habit-view-toggle"
                    onClick={() => setView(current => current === 'dashboard' ? 'habits' : 'dashboard')}
                    aria-label={view === 'dashboard' ? 'Back to habits' : 'Habit dashboard'}
                    title={view === 'dashboard' ? 'Back to habits' : 'Habit dashboard'}
                >
                    {view === 'dashboard' ? <ListChecks size={15} /> : <LayoutDashboard size={15} />}
                    <span className="life-btn-label">{view === 'dashboard' ? 'Habits' : 'Dashboard'}</span>
                </button>
                <button type="button" className="life-btn is-primary" onClick={() => setEditing(blankHabit())} aria-label="New habit">
                    <Plus size={15} /><span className="life-btn-label">New habit</span>
                </button>
            </PageHero>

            {view === 'dashboard' ? (
                <HabitDashboard habits={habits} />
            ) : (
            <>
            <div className="life-stats">
                <StatTile label="Active habits" value={stats.active} hint="Small routines, kept" icon={ListChecks} tint="#6a9bd0" />
                <StatTile label="Done today" value={stats.doneToday} hint={stats.active ? `${stats.active - stats.doneToday} still to go` : 'Add the first one'} icon={CalendarCheck} tint="#7fa650" />
                <StatTile label="Best streak" value={`${stats.bestStreak}d`} hint="Consecutive days" icon={Flame} tint="#d97757" />
                <StatTile label="This week" value={`${stats.weekPct}%`} hint={`${stats.doneWeek} check-ins so far`} icon={Check} tint="#c9a227" />
            </div>

            <div className="panel life-panel">
                <div className="life-scroll">
                    {habits.length === 0 ? (
                        <EmptyState
                            icon={ListChecks}
                            title="No habits yet"
                            hint="Pick one small routine — a walk, a page, a glass of water — and tick it off each day."
                            action={(
                                <button type="button" className="life-btn is-primary" onClick={() => setEditing(blankHabit())}>
                                    <Plus size={14} /> Add a habit
                                </button>
                            )}
                        />
                    ) : (
                        <div className="habit-list">
                            {habits.map(habit => {
                                const streak = streakOf(habit.checks);
                                const done = doneByHabit[habit.id] || 0;
                                return (
                                    <div
                                        className="habit-row"
                                        key={habit.id}
                                        style={{ '--habit-tint': habitColor(habit) }}
                                    >
                                        <div className="habit-info">
                                            <span className="habit-dot" />
                                            <div className="habit-title">
                                                <b>{habit.name}</b>
                                                <small>{habit.category} · {done}/{habit.target} this week</small>
                                                <Progress value={Math.round((done / Math.max(1, habit.target)) * 100)} tint={habitColor(habit)} />
                                            </div>
                                        </div>

                                        <div className="habit-week" role="group" aria-label={`Week for ${habit.name}`}>
                                            {week.map((day, index) => {
                                                const checked = habit.checks.includes(day);
                                                const dayNumber = parseDateOnly(day)?.getDate() || '';
                                                return (
                                                    <button
                                                        type="button"
                                                        key={day}
                                                        className={`habit-day${checked ? ' is-done' : ''}${day === todayISO() ? ' is-today' : ''}`}
                                                        onClick={() => toggleDay(habit, day)}
                                                        title={`${checked ? 'Uncheck' : 'Check'} ${habit.name} for ${formatDay(day)}`}
                                                        aria-pressed={checked}
                                                    >
                                                        <small>{WEEKDAYS[index]}</small>
                                                        <b>{dayNumber}</b>
                                                        {checked && <Check size={10} strokeWidth={3} />}
                                                    </button>
                                                );
                                            })}
                                        </div>

                                        <div className="habit-streak" title={`${streak} day streak`}>
                                            <Flame size={13} />
                                            <b>{streak}</b>
                                            <small>day{streak === 1 ? '' : 's'}</small>
                                        </div>

                                        <div className="habit-actions">
                                            <button type="button" className="life-icon-btn" title="Edit habit" onClick={() => setEditing(habit)}>
                                                <Pencil size={13} />
                                            </button>
                                            <button type="button" className="life-icon-btn is-danger" title="Delete habit" onClick={() => deleteHabit(habit)}>
                                                <Trash2 size={13} />
                                            </button>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>

            </>
            )}

            {editing && (
                <HabitEditor
                    habit={editing}
                    onClose={() => setEditing(null)}
                    onSave={saveHabit}
                    onDelete={deleteHabit}
                />
            )}
        </div>
    );
}
