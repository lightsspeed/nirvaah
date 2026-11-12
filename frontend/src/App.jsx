import React, { useEffect, useLayoutEffect, useMemo, useState, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import axios from 'axios';
import {
    LayoutDashboard, ArrowLeftRight, Wallet, Target, TrendingUp, CreditCard,
    LogOut, Plus, Trash2, Pencil, Menu, X, ChartNoAxesCombined, Search,
    Bell, Eye, EyeOff, ArrowUpRight, ArrowDownLeft, CalendarDays, MoreHorizontal,
    ChevronDown, Landmark, RefreshCw, Filter, TrendingDown, Check, Calendar,
    FileText, CheckSquare, Activity, SlidersHorizontal, Tag, RotateCcw,
    Sun, Moon, Laptop, BookOpen,
} from 'lucide-react';
import {
    ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
    PieChart, Pie, Cell,
    AreaChart, Area, LineChart, Line, Legend, ReferenceLine, Dot, LabelList,
} from 'recharts';
import GlobalSearch from './GlobalSearch';
import BrandAiIcon from './BrandAiIcon';
import AssistantPage from './AssistantPage';
import NotesPage from './life/NotesPage';
import TasksPage from './life/TasksPage';
import JournalPage from './life/JournalPage';
import { useCollection, NOTES_KEY, TASKS_KEY, EVENTS_KEY, logActivity, startSyncWatch, REMOTE_CHANGE } from './life/store';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8001/api';
const http = axios.create({ baseURL: API });

// Decimals are real money: a record with paise shows two of them, a whole
// rupee amount shows none. Rounding to 0 here is what hid ₹706.82 as ₹707.
const MONEY_PAISE = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 });
const MONEY_WHOLE = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 0, maximumFractionDigits: 0 });
const money = n => {
    const value = Number(n || 0);
    return (Math.abs(value - Math.round(value)) > 0.004 ? MONEY_PAISE : MONEY_WHOLE).format(value);
};
const today = () => new Date().toISOString().slice(0, 10);
const yesterday = () => {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return d.toISOString().slice(0, 10);
};
const thisMonthStr = () => today().slice(0, 7);

// Month picker options in the same shape as every other dropdown.
const monthOptions = (back = 11, ahead = 6) => {
    const now = new Date();
    const out = [];
    for (let i = -back; i <= ahead; i++) {
        const d = new Date(now.getFullYear(), now.getMonth() + i, 1);
        const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
        out.push({ value, label: d.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' }) });
    }
    return out;
};

const monthLabel = value => {
    if (!value) return '—';
    const [y, m] = String(value).split('-');
    const d = new Date(Number(y), Number(m) - 1, 1);
    return d.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });
};

const getCurrentMonthRange = () => {
    const todayDate = new Date();
    const curYear = todayDate.getFullYear();
    const curMonth = todayDate.getMonth();
    const mStr = `${curYear}-${String(curMonth + 1).padStart(2, '0')}`;
    const lastDay = new Date(curYear, curMonth + 1, 0).getDate();
    return {
        preset: 'this_month',
        startDate: `${mStr}-01`,
        endDate: `${mStr}-${String(lastDay).padStart(2, '0')}`,
        label: todayDate.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' }),
        month: mStr,
    };
};

// Default categories and payment methods
const DEFAULT_EXPENSE_CATS = [
    'Car Maintenance', 'Clothes', 'Dining Out', 'Doctor Visits', 'Education',
    'Electricity', 'Entertainment', 'Fuel', 'Gas', 'Groceries', 'Grooming',
    'Health Insurance', 'Hobbies', 'Household Items', 'Medications', 'Misc',
    'Mobile Bills', 'Office eats', 'Subscription', 'Travel', 'Other',
];
const DEFAULT_INCOME_CATS = ['Salary', 'Interest', 'Transferred', 'Stocks', 'Freelance', 'Other'];
const DEFAULT_PAYMENT_METHODS = ['SBI', 'HDFC', 'Cash', 'Debit Card', 'Credit Card', 'Net Banking', 'Bank Transfer', 'Other'];

const EXPENSE_CATS = DEFAULT_EXPENSE_CATS;
const INCOME_CATS = DEFAULT_INCOME_CATS;
const ALL_CATS = Array.from(new Set([...EXPENSE_CATS, ...INCOME_CATS])).sort();

const CHART_COLORS = [
    'var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)',
    'var(--chart-6)', 'var(--chart-7)', 'var(--chart-8)', 'var(--chart-9)', 'var(--chart-10)',
];

// ── Category & Payment Color Coding ──────────────────────────────────────────
const CATEGORY_COLORS = {
    Salary: { bg: '#eff6ff', text: '#1d4ed8', border: '#bfdbfe', dot: '#2563eb' },
    Interest: { bg: '#ecfdf5', text: '#047857', border: '#a7f3d0', dot: 'var(--chart-2)' },
    Freelance: { bg: '#f5f3ff', text: '#6d28d9', border: '#ddd6fe', dot: '#8b5cf6' },
    Stocks: { bg: '#e0f2fe', text: '#0369a1', border: '#bae6fd', dot: '#0284c7' },
    Transferred: { bg: '#f1f5f9', text: '#475569', border: '#cbd5e1', dot: 'var(--muted-foreground)' },
    Groceries: { bg: '#ecfdf5', text: '#059669', border: '#a7f3d0', dot: 'var(--chart-2)' },
    'Dining Out': { bg: '#fff7ed', text: '#ea580c', border: '#fed7aa', dot: '#f97316' },
    'Office eats': { bg: '#fffbeb', text: '#d97706', border: '#fef3c7', dot: '#f59e0b' },
    'Household Items': { bg: '#f0fdf4', text: '#16a34a', border: '#bbf7d0', dot: '#22c55e' },
    Fuel: { bg: '#fef3c7', text: '#b45309', border: '#fde68a', dot: '#f59e0b' },
    'Car Maintenance': { bg: '#fff1f2', text: '#e11d48', border: '#fecdd3', dot: '#f43f5e' },
    Electricity: { bg: '#fef9c3', text: '#ca8a04', border: '#fef08a', dot: '#eab308' },
    Gas: { bg: '#ffedd5', text: '#c2410c', border: '#fed7aa', dot: '#f97316' },
    'Mobile Bills': { bg: '#eef2ff', text: '#4f46e5', border: '#c7d2fe', dot: '#6366f1' },
    Medications: { bg: '#fef2f2', text: '#dc2626', border: '#fecaca', dot: 'var(--chart-1)' },
    'Doctor Visits': { bg: '#ffe4e6', text: '#be123c', border: '#fda4af', dot: '#f43f5e' },
    'Health Insurance': { bg: '#ecfeff', text: '#0891b2', border: '#a5f3fc', dot: '#06b6d4' },
    Grooming: { bg: '#fdf2f8', text: '#db2777', border: '#fbcfe8', dot: '#ec4899' },
    Clothes: { bg: '#fce7f3', text: '#be185d', border: '#fbcfe8', dot: '#ec4899' },
    Entertainment: { bg: '#f5f3ff', text: '#7c3aed', border: '#ddd6fe', dot: '#8b5cf6' },
    Hobbies: { bg: '#ede9fe', text: '#6d28d9', border: '#ddd6fe', dot: '#8b5cf6' },
    Subscription: { bg: '#fae8ff', text: '#a21caf', border: '#f5d0fe', dot: '#d946ef' },
    Education: { bg: '#e0f2fe', text: '#0284c7', border: '#bae6fd', dot: '#0ea5e9' },
    Travel: { bg: '#fff1f2', text: '#e11d48', border: '#fecdd3', dot: '#f43f5e' },
    Misc: { bg: '#f1f5f9', text: '#475569', border: '#cbd5e1', dot: 'var(--muted-foreground)' },
    Other: { bg: '#f3f4f6', text: '#4b5563', border: '#e5e7eb', dot: 'var(--muted-foreground)' },
};

// Categories read warm, payment channels read cool — two families that never
// collide, so a chip's colour tells you what kind of tag it is.
const CATEGORY_TINTS = ['var(--chart-1)', 'var(--chart-3)', 'var(--chart-5)', 'var(--chart-8)', 'var(--chart-9)', 'var(--chart-10)'];
const CHIP_TINTS = CATEGORY_TINTS;

const hashTint = str => {
    let hash = 0;
    const value = String(str || '');
    for (let i = 0; i < value.length; i++) hash = value.charCodeAt(i) + ((hash << 5) - hash);
    return CHIP_TINTS[Math.abs(hash) % CHIP_TINTS.length];
};

// Chips are tinted from one accent colour, so they stay legible in light AND dark.
const chipStyle = dot => ({
    background: `color-mix(in srgb, ${dot} 13%, transparent)`,
    color: `color-mix(in srgb, ${dot} 74%, var(--text-main))`,
    border: `1px solid color-mix(in srgb, ${dot} 26%, transparent)`,
});

// Payment pills are solid and vibrant; the hue is derived from the method name
// so a user-added method still gets a distinct, readable colour.
const PAY_VIBRANT = ['#2563eb', '#0d9488', '#4f46e5', '#0891b2', '#7c3aed', '#0284c7', '#3d5afe', '#0e7490'];
const vibrantPill = str => {
    let hash = 0;
    const value = String(str || '');
    for (let i = 0; i < value.length; i++) hash = value.charCodeAt(i) + ((hash << 5) - hash);
    // Same shape as a category pill (neutral surface, coloured label) — only
    // the hue differs, so payment and category chips read as one family.
    return chipStyle(PAY_VIBRANT[Math.abs(hash) % PAY_VIBRANT.length]);
};

// Fourteen hue anchors around the wheel. The hue is hashed from the name, so a
// category created today is coloured the moment it exists — no registration.
const CAT_HUES = [10, 24, 38, 50, 70, 96, 148, 170, 192, 212, 238, 262, 288, 320];

const categoryHue = cat => {
    const value = String(cat || '').toLowerCase().trim();
    let h = 0;
    for (let i = 0; i < value.length; i++) h = (h * 33 + value.charCodeAt(i)) >>> 0;
    return CAT_HUES[h % CAT_HUES.length];
};

const getCategoryStyle = cat => ({ '--cat-h': categoryHue(cat) });

const getCategoryDotColor = cat => `hsl(${categoryHue(cat)} 55% 46%)`;

const PAYMENT_DOTS = {
    UPI: 'var(--chart-5)',
    HDFC: 'var(--chart-4)',
    ICICI: '#d98fb0',
    SBI: 'var(--chart-2)',
    'Bank Transfer': 'var(--chart-4)',
    'Net Banking': 'var(--chart-2)',
    Cash: 'var(--chart-3)',
    'Credit Card': 'var(--chart-1)',
    'Debit Card': '#6fa8a0',
};

const getPaymentStyle = method => vibrantPill(method || 'unknown');

const getPaymentChartColor = (method, index = 0) => {
    if (!method) return hashTint(`p${index}`);
    const key = Object.keys(PAYMENT_DOTS).find(k => method.toUpperCase().includes(k.toUpperCase()));
    return key ? PAYMENT_DOTS[key] : hashTint(method);
};

const PAGE_SINGULAR = {
    Dashboard: 'entry',
    Transactions: 'transaction',
    Budgets: 'budget',
    'Savings goals': 'goal',
    Investments: 'investment',
    Liabilities: 'liability',
    Reports: 'report',
    Notes: 'note',
    Tasks: 'task',
    Journal: 'event',
};
// "Liabilities" must not become "liabilitie".
const singularPage = page => PAGE_SINGULAR[page] || page.replace(/ies$/i, 'y').replace(/s$/i, '').toLowerCase();

const groups = [
    ['OVERVIEW', ['Dashboard', 'Assistant']],
    ['MONEY MANAGEMENT', ['Transactions', 'Budgets', 'Reports']],
    ['PLANNING', ['Savings goals', 'Investments', 'Liabilities']],
    ['LIFE & NOTES', ['Notes', 'Tasks', 'Journal']],
];
// One colour per page — a small, consistent signal rather than a wall of icons.
const PAGE_TINTS = {
    Dashboard: '#3d5bff',
    Assistant: '#ff7a1a',
    Transactions: '#0e9c8a',
    Budgets: '#c58a1b',
    Reports: '#6c5ce7',
    'Savings goals': '#3f8f4f',
    Investments: '#2f80c8',
    Liabilities: '#c0485c',
    Notes: '#8a5bd6',
    Tasks: '#d9713f',
    Journal: '#b2508f',
};

// Page heading: the page's own name, with a proper name for the assistant.
const PAGE_TITLES = { Assistant: 'Nirvaah AI' };
const PAGE_SUBTEXT = {
    Dashboard: "A clear view of where you stand and where you're going.",
    Assistant: 'Ask about your records, or tell me what to change.',
    Transactions: 'Every rupee, categorised and searchable.',
    Budgets: 'Monthly limits per category, with what is left to spend.',
    Reports: 'Where the money went, across any period you pick.',
    'Savings goals': 'What you are setting money aside for, and how close you are.',
    Investments: 'What you hold, what it cost, and what it is worth now.',
    Liabilities: 'Loans and dues, with the monthly commitment they carry.',
    Notes: 'A quiet place for decisions, plans and half-formed money thoughts.',
    Tasks: 'Small, specific actions. Bills to pay, things to check, money to move.',
    Journal: 'Life events, logged as they happen — the story behind the numbers.',
};
const pageTitle = page => PAGE_TITLES[page] || page;
const pageSubtext = page => PAGE_SUBTEXT[page] || 'Your financial picture, organized in one place.';

const icons = {
    Dashboard: LayoutDashboard, Transactions: ArrowLeftRight, Budgets: Wallet,
    'Savings goals': Target, Investments: TrendingUp, Liabilities: CreditCard, Reports: ChartNoAxesCombined,
    Notes: FileText, Tasks: CheckSquare, Journal: BookOpen, Assistant: BrandAiIcon,
};

// ── Custom Tooltip for Charts ────────────────────────────────────────────────
const ChartTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null;
    return (
        <div className="chart-tooltip">
            <div className="chart-tooltip-label">{label}</div>
            {payload.map((p, i) => (
                <div key={i} className="chart-tooltip-row">
                    <span style={{ color: p.color }}>■</span>
                    <span>{p.name}</span>
                    <b>{money(p.value)}</b>
                </div>
            ))}
        </div>
    );
};

// ── Number Rotation Animation Component (Odometer / CountUp) ─────────────────
function AnimatedNumber({ value, formatter = money, duration = 400 }) {
    const num = Number(value || 0);
    const [displayVal, setDisplayVal] = useState(num);
    const prevValRef = useRef(num);

    useEffect(() => {
        const startVal = prevValRef.current;
        const endVal = Number(value || 0);
        prevValRef.current = endVal;

        if (startVal === endVal) {
            setDisplayVal(endVal);
            return;
        }

        const startTime = performance.now();
        let animId;

        const tick = now => {
            const elapsed = now - startTime;
            const progress = Math.min(1, elapsed / duration);
            const ease = 1 - Math.pow(1 - progress, 3);
            const current = startVal + (endVal - startVal) * ease;
            setDisplayVal(current);

            if (progress < 1) {
                animId = requestAnimationFrame(tick);
            } else {
                setDisplayVal(endVal);
            }
        };

        animId = requestAnimationFrame(tick);
        return () => cancelAnimationFrame(animId);
    }, [value, duration]);

    return <span key={value} className="rolling-number">{formatter(displayVal)}</span>;
}

// ── Custom Dropdown (Linear / Stripe fintech design with Full Keyboard Nav) ──
function CustomSelect({
    value,
    onChange,
    options,
    placeholder = 'Select…',
    fullWidth = false,
    align = 'left',
    dropUp = false,
    icon: Icon = null,
    tabIndex = 0,
}) {
    const [open, setOpen] = useState(false);
    const [isDropUp, setIsDropUp] = useState(dropUp);
    const [isAlignRight, setIsAlignRight] = useState(align === 'right');
    const [fixedPos, setFixedPos] = useState(null);
    const [highlightedIndex, setHighlightedIndex] = useState(0);
    const ref = useRef(null);
    const triggerRef = useRef(null);
    const itemRefs = useRef([]);
    const menuRef = useRef(null);
    const typeaheadBuffer = useRef('');
    const typeaheadTimer = useRef(null);

    // Normalize options into { value, label }
    const normalized = useMemo(() => {
        return options.map(opt => (typeof opt === 'string' ? { value: opt, label: opt } : opt));
    }, [options]);

    // Keep highlightedIndex in sync with selected value
    useEffect(() => {
        const idx = normalized.findIndex(o => o.value === value);
        setHighlightedIndex(idx >= 0 ? idx : 0);
    }, [value, normalized]);

    // Close when clicking outside
    useEffect(() => {
        const onMouseDown = e => {
            const inTrigger = ref.current && ref.current.contains(e.target);
            const inMenu = menuRef.current && menuRef.current.contains(e.target);
            if (!inTrigger && !inMenu) setOpen(false);
        };
        if (open) {
            document.addEventListener('mousedown', onMouseDown);
        }
        return () => {
            document.removeEventListener('mousedown', onMouseDown);
        };
    }, [open]);

    // Keep the anchored menu under its trigger while anything scrolls.
    useEffect(() => {
        if (!open) return;
        const onMove = () => updatePosition();
        window.addEventListener('scroll', onMove, true);
        window.addEventListener('resize', onMove);
        return () => {
            window.removeEventListener('scroll', onMove, true);
            window.removeEventListener('resize', onMove);
        };
    }, [open]);

    // Auto-scroll highlighted option into view smoothly
    useEffect(() => {
        if (open && itemRefs.current[highlightedIndex]) {
            itemRefs.current[highlightedIndex].scrollIntoView({
                block: 'nearest',
                behavior: 'smooth',
            });
        }
    }, [highlightedIndex, open]);

    // Dynamic positioning to prevent clipping
    // Menus are anchored to the viewport, not the parent: a dropdown inside a
    // scrolling modal or a clipped table cell must still open fully.
    const MENU_GAP = 6;
    const updatePosition = () => {
        const anchor = triggerRef.current || ref.current;
        if (!anchor) return;
        const rect = anchor.getBoundingClientRect();
        const spaceBelow = window.innerHeight - rect.bottom;
        const spaceAbove = rect.top;
        // Open towards the roomier side, then clamp to the space that is really
        // there — a forced minimum used to push the panel past the viewport.
        const up = dropUp || (spaceBelow < 300 && spaceAbove > spaceBelow);
        const available = (up ? spaceAbove : spaceBelow) - MENU_GAP - 12;
        const maxHeight = Math.min(300, Math.max(96, available));
        let left = rect.left;
        const width = rect.width;
        const overflowRight = left + width > window.innerWidth - 12;
        if (align === 'right' || overflowRight) left = Math.max(12, rect.right - width);
        setFixedPos({
            left,
            width,
            maxHeight,
            ...(up
                ? { bottom: Math.max(12, window.innerHeight - rect.top + MENU_GAP) }
                : { top: rect.bottom + MENU_GAP }),
        });
        setIsDropUp(up);
        setIsAlignRight(align === 'right' || overflowRight);
    };

    const toggleOpen = () => {
        if (!open) {
            updatePosition();
            const idx = normalized.findIndex(o => o.value === value);
            setHighlightedIndex(idx >= 0 ? idx : 0);
            setOpen(true);
        } else {
            setOpen(false);
        }
    };

    // Typeahead search handler (cycles on repeated character, multi-character search)
    const handleTypeahead = char => {
        if (!normalized || normalized.length === 0) return;
        const lowerChar = char.toLowerCase();
        if (typeaheadTimer.current) clearTimeout(typeaheadTimer.current);

        const prevBuffer = typeaheadBuffer.current;
        const activeIdx = highlightedIndex >= 0 && highlightedIndex < normalized.length
            ? highlightedIndex
            : Math.max(0, normalized.findIndex(o => o.value === value));

        const currentItemLabel = (normalized[activeIdx]?.label || String(normalized[activeIdx]?.value || '')).toLowerCase();

        // Check if this is a repeat of the same character:
        // 1) Either buffer already consists entirely of lowerChar (e.g. 'c' then 'c'),
        // 2) OR buffer is empty but the currently selected item already starts with lowerChar
        const isRepeatedChar = (prevBuffer.length > 0 && prevBuffer.split('').every(c => c === lowerChar)) ||
                               (prevBuffer.length === 0 && currentItemLabel.startsWith(lowerChar));

        let matchIdx = -1;

        if (isRepeatedChar) {
            // Cycle forward from current item to next item starting with lowerChar
            const startIndex = (activeIdx + 1) % normalized.length;
            for (let i = 0; i < normalized.length; i++) {
                const checkIdx = (startIndex + i) % normalized.length;
                const label = (normalized[checkIdx].label || String(normalized[checkIdx].value || '')).toLowerCase();
                if (label.startsWith(lowerChar)) {
                    matchIdx = checkIdx;
                    break;
                }
            }
            typeaheadBuffer.current = lowerChar;
        } else {
            // Multi-character search or first press of a new letter
            const search = prevBuffer + lowerChar;
            typeaheadBuffer.current = search;

            // 1. Try prefix match with full typed string
            matchIdx = normalized.findIndex(o => (o.label || String(o.value || '')).toLowerCase().startsWith(search));

            // 2. If no match and search length > 1, treat incoming key as start of a fresh single-char search
            if (matchIdx === -1 && search.length > 1) {
                typeaheadBuffer.current = lowerChar;
                matchIdx = normalized.findIndex(o => (o.label || String(o.value || '')).toLowerCase().startsWith(lowerChar));
            }

            // 3. Substring fallback
            if (matchIdx === -1) {
                matchIdx = normalized.findIndex(o => (o.label || String(o.value || '')).toLowerCase().includes(typeaheadBuffer.current));
            }
        }

        typeaheadTimer.current = setTimeout(() => {
            typeaheadBuffer.current = '';
        }, 900);

        if (matchIdx !== -1) {
            setHighlightedIndex(matchIdx);
            onChange(normalized[matchIdx].value);
        }
    };

    // Full keyboard navigation
    const handleKeyDown = e => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (!open) {
                updatePosition();
                const idx = normalized.findIndex(o => o.value === value);
                setHighlightedIndex(idx >= 0 ? idx : 0);
                setOpen(true);
            } else {
                setHighlightedIndex(prev => (prev + 1) % normalized.length);
            }
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (!open) {
                updatePosition();
                const idx = normalized.findIndex(o => o.value === value);
                setHighlightedIndex(idx >= 0 ? idx : 0);
                setOpen(true);
            } else {
                setHighlightedIndex(prev => (prev - 1 + normalized.length) % normalized.length);
            }
        } else if (e.key === 'Enter') {
            if (open) {
                e.preventDefault();
                e.stopPropagation();
                if (highlightedIndex >= 0 && highlightedIndex < normalized.length) {
                    onChange(normalized[highlightedIndex].value);
                }
                setOpen(false);
            } else {
                // If inside a form and user hits Enter on a closed select, submit the form!
                const form = ref.current?.closest('form');
                if (form) {
                    e.preventDefault();
                    form.requestSubmit();
                } else {
                    e.preventDefault();
                    updatePosition();
                    const idx = normalized.findIndex(o => o.value === value);
                    setHighlightedIndex(idx >= 0 ? idx : 0);
                    setOpen(true);
                }
            }
        } else if (e.key === ' ') {
            e.preventDefault();
            if (open) {
                if (highlightedIndex >= 0 && highlightedIndex < normalized.length) {
                    onChange(normalized[highlightedIndex].value);
                }
                setOpen(false);
            } else {
                updatePosition();
                const idx = normalized.findIndex(o => o.value === value);
                setHighlightedIndex(idx >= 0 ? idx : 0);
                setOpen(true);
            }
        } else if (e.key === 'Tab') {
            if (open) {
                if (highlightedIndex >= 0 && highlightedIndex < normalized.length) {
                    onChange(normalized[highlightedIndex].value);
                }
                setOpen(false);
                // Allow Tab default action to naturally advance to next field
            }
        } else if (e.key === 'Escape') {
            if (open) {
                e.preventDefault();
                e.stopPropagation();
                setOpen(false);
            }
        } else if (e.key === 'Home' && open) {
            e.preventDefault();
            setHighlightedIndex(0);
        } else if (e.key === 'End' && open) {
            e.preventDefault();
            setHighlightedIndex(normalized.length - 1);
        } else if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
            handleTypeahead(e.key);
        }
    };

    const selectedOpt = normalized.find(o => o.value === value);

    return (
        <div className={`custom-select ${fullWidth ? 'full-width' : ''}`} ref={ref}>
            <button
                ref={triggerRef}
                type="button"
                className={`custom-select-trigger ${open ? 'active' : ''}`}
                onClick={toggleOpen}
                onKeyDown={handleKeyDown}
                aria-haspopup="listbox"
                aria-expanded={open}
                tabIndex={tabIndex}
            >
                <span className="trigger-content">
                    {Icon && <span className="trigger-icon"><Icon size={14} /></span>}
                    <span>{selectedOpt ? selectedOpt.label : placeholder}</span>
                </span>
                <ChevronDown size={14} className="trigger-arrow" />
            </button>

            {open && createPortal(
                <div
                    ref={menuRef}
                    className={`custom-select-menu ${isAlignRight ? 'align-right' : ''} ${isDropUp ? 'drop-up' : ''} ${fixedPos ? 'is-fixed' : ''}`}
                    role="listbox"
                    style={fixedPos ? {
                        '--menu-left': `${fixedPos.left}px`,
                        '--menu-w': `${fixedPos.width}px`,
                        '--menu-maxh': `${fixedPos.maxHeight}px`,
                        '--menu-top': fixedPos.top != null ? `${fixedPos.top}px` : 'auto',
                        '--menu-bottom': fixedPos.bottom != null ? `${fixedPos.bottom}px` : 'auto',
                    } : undefined}
                >
                    {normalized.map((opt, idx) => {
                        const isSelected = opt.value === value;
                        const isHighlighted = idx === highlightedIndex;
                        return (
                            <button
                                key={opt.value}
                                ref={el => { itemRefs.current[idx] = el; }}
                                type="button"
                                role="option"
                                aria-selected={isSelected}
                                className={`custom-select-item ${isSelected ? 'selected' : ''} ${isHighlighted ? 'highlighted' : ''}`}
                                onMouseEnter={() => setHighlightedIndex(idx)}
                                onMouseDown={e => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    onChange(opt.value);
                                    setOpen(false);
                                    triggerRef.current?.focus();
                                }}
                                onClick={e => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    onChange(opt.value);
                                    setOpen(false);
                                    triggerRef.current?.focus();
                                }}
                            >
                                <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                    {opt.dot && <span className="cat-dot" style={{ background: opt.dot }} />}
                                    {opt.label}
                                </span>
                                {isSelected && <Check size={14} className="item-check" />}
                            </button>
                        );
                    })}
                </div>,
                document.body
            )}
        </div>
    );
}

// ── Segmented Tabs (the single tab control — DESIGN.md · Components) ─────────
// Pill track, 28px items, sliding indicator. Fixed-width slots are achieved by
// measuring the active item, so a count or label change never reflows the row.
function SegmentedTabs({ items, value, onChange, ariaLabel = 'View', className = '' }) {
    const trackRef = useRef(null);
    const [indicator, setIndicator] = useState({ left: 0, width: 0, ready: false });

    const measure = useCallback(() => {
        const track = trackRef.current;
        if (!track) return;
        const active = track.querySelector('[data-active="true"]');
        if (!active) return;
        setIndicator({ left: active.offsetLeft, width: active.offsetWidth, ready: true });
    }, []);

    useLayoutEffect(() => {
        measure();
    }, [measure, value, items.length]);

    useEffect(() => {
        if (typeof ResizeObserver === 'undefined') return;
        const ro = new ResizeObserver(measure);
        if (trackRef.current) ro.observe(trackRef.current);
        return () => ro.disconnect();
    }, [measure]);

    return (
        <div
            ref={trackRef}
            className={`seg ${className}`}
            role="tablist"
            aria-label={ariaLabel}
        >
            <span
                className="seg-indicator"
                aria-hidden="true"
                style={{
                    width: indicator.width,
                    transform: `translateX(${indicator.left}px)`,
                    opacity: indicator.ready ? 1 : 0,
                }}
            />
            {items.map(item => {
                const active = item.value === value;
                return (
                    <button
                        key={item.value}
                        type="button"
                        role="tab"
                        aria-selected={active}
                        data-active={active ? 'true' : 'false'}
                        className={`seg-item ${active ? 'is-active' : ''}`}
                        title={item.title || item.label}
                        onClick={() => onChange(item.value)}
                    >
                        {item.icon}
                        <span>{item.label}</span>
                        {item.count > 0 && <span className="seg-count">{item.count}</span>}
                    </button>
                );
            })}
        </div>
    );
}

// ── Unified Date Range Filter Component ──────────────────────────────────────
function DateRangeFilter({ range, onChange, txRange }) {
    const [open, setOpen] = useState(false);
    const [customStart, setCustomStart] = useState(range.startDate || '');
    const [customEnd, setCustomEnd] = useState(range.endDate || '');
    const popoverRef = useRef(null);
    const panelRef = useRef(null);
    const [panelPos, setPanelPos] = useState(null);

    const placePanel = () => {
        const trigger = popoverRef.current?.querySelector('.date-range-trigger');
        if (!trigger) return;
        const r = trigger.getBoundingClientRect();
        const width = Math.min(340, window.innerWidth - 24);
        const left = Math.min(Math.max(12, r.right - width), window.innerWidth - width - 12);
        const spaceBelow = window.innerHeight - r.bottom - 12;
        const up = spaceBelow < 300 && r.top > spaceBelow;
        setPanelPos({
            left,
            width,
            ...(up ? { bottom: window.innerHeight - r.top + 6 } : { top: r.bottom + 6 }),
            maxHeight: Math.max(220, Math.min(560, (up ? r.top : spaceBelow) - 12)),
        });
    };

    useEffect(() => {
        setCustomStart(range.startDate || '');
        setCustomEnd(range.endDate || '');
    }, [range]);

    useEffect(() => {
        if (!open) return;
        const onMove = () => placePanel();
        window.addEventListener('scroll', onMove, true);
        window.addEventListener('resize', onMove);
        return () => {
            window.removeEventListener('scroll', onMove, true);
            window.removeEventListener('resize', onMove);
        };
    }, [open]);

    useEffect(() => {
        const onMouseDown = e => {
            const inTrigger = popoverRef.current && popoverRef.current.contains(e.target);
            const inPanel = panelRef.current && panelRef.current.contains(e.target);
            if (!inTrigger && !inPanel) setOpen(false);
        };
        if (open) document.addEventListener('mousedown', onMouseDown);
        return () => document.removeEventListener('mousedown', onMouseDown);
    }, [open]);

    // Compute preset dates
    const applyPreset = preset => {
        const todayDate = new Date();
        const curYear = todayDate.getFullYear();
        const curMonth = todayDate.getMonth(); // 0-indexed

        if (preset === 'all') {
            onChange({
                preset: 'all',
                startDate: txRange?.min_date || '2026-01-01',
                endDate: txRange?.max_date || today(),
                label: 'All Time',
                month: 'all',
            });
        } else if (preset === 'this_month') {
            const mStr = thisMonthStr();
            const lastDay = new Date(curYear, curMonth + 1, 0).getDate();
            onChange({
                preset: 'this_month',
                startDate: `${mStr}-01`,
                endDate: `${mStr}-${String(lastDay).padStart(2, '0')}`,
                label: new Date().toLocaleDateString('en-IN', { month: 'short', year: 'numeric' }),
                month: mStr,
            });
        } else if (preset === 'last_month') {
            const prevDate = new Date(curYear, curMonth - 1, 1);
            const prevYear = prevDate.getFullYear();
            const prevMonth = prevDate.getMonth();
            const mStr = `${prevYear}-${String(prevMonth + 1).padStart(2, '0')}`;
            const lastDay = new Date(prevYear, prevMonth + 1, 0).getDate();
            onChange({
                preset: 'last_month',
                startDate: `${mStr}-01`,
                endDate: `${mStr}-${String(lastDay).padStart(2, '0')}`,
                label: prevDate.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' }),
                month: mStr,
            });
        } else if (preset === '3m') {
            const startD = new Date(curYear, curMonth - 2, 1);
            const sStr = `${startD.getFullYear()}-${String(startD.getMonth() + 1).padStart(2, '0')}-01`;
            onChange({
                preset: '3m',
                startDate: sStr,
                endDate: today(),
                label: 'Last 3 Months',
                month: null,
            });
        } else if (preset === '6m') {
            const startD = new Date(curYear, curMonth - 5, 1);
            const sStr = `${startD.getFullYear()}-${String(startD.getMonth() + 1).padStart(2, '0')}-01`;
            onChange({
                preset: '6m',
                startDate: sStr,
                endDate: today(),
                label: 'Last 6 Months',
                month: null,
            });
        } else if (preset === 'this_year') {
            onChange({
                preset: 'this_year',
                startDate: `${curYear}-01-01`,
                endDate: `${curYear}-12-31`,
                label: `Year ${curYear}`,
                month: null,
            });
        }
        setOpen(false);
    };

    const applyCustom = () => {
        if (!customStart || !customEnd) return;
        onChange({
            preset: 'custom',
            startDate: customStart,
            endDate: customEnd,
            label: `${customStart.slice(5)} → ${customEnd.slice(5)}`,
            month: null,
        });
        setOpen(false);
    };

    return (
        <div className="date-range-filter" ref={popoverRef}>
            <button
                type="button"
                className={`date-range-trigger ${open ? 'active' : ''}`}
                onClick={() => { placePanel(); setOpen(!open); }}
            >
                <span className="cal-icon"><Calendar size={14} /></span>
                <span className="range-text">{range.label || 'Select period'}</span>
                <ChevronDown size={13} style={{ color: 'var(--muted-foreground)' }} />
            </button>

            {open && createPortal(
                <div
                    ref={panelRef}
                    className="date-range-popover is-anchored"
                    style={panelPos ? {
                        '--drp-left': `${panelPos.left}px`,
                        '--drp-w': `${panelPos.width}px`,
                        '--drp-maxh': `${panelPos.maxHeight}px`,
                        '--drp-top': panelPos.top != null ? `${panelPos.top}px` : 'auto',
                        '--drp-bottom': panelPos.bottom != null ? `${panelPos.bottom}px` : 'auto',
                    } : undefined}
                    onMouseDown={e => e.stopPropagation()}
                >
                    <div className="popover-head">
                        <small>CHOOSE DATE RANGE</small>
                        <span style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>{txRange?.total_count || 0} total txns</span>
                    </div>

                    <div className="date-range-presets">
                        {[
                            ['this_month', 'This Month'],
                            ['last_month', 'Last Month'],
                            ['3m', 'Last 3 Months'],
                            ['6m', 'Last 6 Months'],
                            ['this_year', 'This Year'],
                            ['all', 'All Time'],
                        ].map(([id, name]) => (
                            <button
                                key={id}
                                type="button"
                                className={`date-range-preset-btn ${range.preset === id ? 'active' : ''}`}
                                onClick={e => {
                                    e.stopPropagation();
                                    applyPreset(id);
                                }}
                            >
                                {name}
                            </button>
                        ))}
                    </div>

                    <div className="date-range-custom-box">
                        <span style={{ fontSize: 13, fontWeight: 700, color: '#6b7280', textTransform: 'uppercase' }}>
                            Custom Range
                        </span>
                        <div className="date-range-inputs-row">
                            <label className="date-range-input-field">
                                <span>From</span>
                                <input
                                    type="date"
                                    value={customStart}
                                    min={txRange?.min_date || ''}
                                    max={customEnd || txRange?.max_date || ''}
                                    onChange={e => setCustomStart(e.target.value)}
                                />
                            </label>
                            <label className="date-range-input-field">
                                <span>To</span>
                                <input
                                    type="date"
                                    value={customEnd}
                                    min={customStart || txRange?.min_date || ''}
                                    max={txRange?.max_date || ''}
                                    onChange={e => setCustomEnd(e.target.value)}
                                />
                            </label>
                        </div>
                        <div className="date-range-actions">
                            <button type="button" className="soft btn-sm" onClick={() => setOpen(false)}>Cancel</button>
                            <button type="button" className="blue btn-sm" onClick={e => { e.stopPropagation(); applyCustom(); }}>Apply Range</button>
                        </div>
                    </div>
                </div>,
                document.body
            )}
        </div>
    );
}

// ── Main Application Component ───────────────────────────────────────────────
export default function App() {
    const [token, setToken] = useState(localStorage.getItem('moneta_token') || '');
    const [user, setUser] = useState(null);

    // Two devices, one truth: poll a record fingerprint and re-hydrate on change.
    useEffect(() => {
        if (token) startSyncWatch();
    }, [token]);

    // POINT 2: PERSIST CURRENT PAGE ACROSS REFRESH
    const [page, setPage] = useState(() => {
        const hash = window.location.hash.replace('#', '');
        const validPages = ['Dashboard', 'Transactions', 'Budgets', 'Savings goals', 'Investments', 'Liabilities', 'Notes', 'Tasks', 'Journal', 'Reports'];
        const matched = validPages.find(p => p.toLowerCase().replace(/\s+/g, '-') === hash);
        if (matched) return matched;
        return localStorage.getItem('moneta_page') || 'Dashboard';
    });

    const navigateTo = useCallback((p) => {
        setPage(p);
        localStorage.setItem('moneta_page', p);
        window.location.hash = p.toLowerCase().replace(/\s+/g, '-');
    }, []);

    // Listen to hash change for browser back/forward buttons
    useEffect(() => {
        const onHashChange = () => {
            const hash = window.location.hash.replace('#', '');
            const validPages = ['Dashboard', 'Transactions', 'Budgets', 'Savings goals', 'Investments', 'Liabilities', 'Notes', 'Tasks', 'Journal', 'Reports'];
            const matched = validPages.find(p => p.toLowerCase().replace(/\s+/g, '-') === hash);
            if (matched && matched !== page) {
                setPage(matched);
                localStorage.setItem('moneta_page', matched);
            }
        };
        window.addEventListener('hashchange', onHashChange);
        return () => window.removeEventListener('hashchange', onHashChange);
    }, [page]);

    // POINT 4: UNIFIED DATE RANGE STATE FOR ALL PAGES (Default to Current Month)
    const [range, setRange] = useState(getCurrentMonthRange);

    const [d, setD] = useState(null);
    const [tx, setTx] = useState([]);
    const [budgets, setBudgets] = useState([]);
    const [goals, setGoals] = useState([]);
    const [investments, setInvestments] = useState([]);
    const [liabilities, setLiabilities] = useState([]);
    const [cashflow, setCashflow] = useState([]);
    const [analytics, setAnalytics] = useState(null);
    const [txRange, setTxRange] = useState({ min_date: null, max_date: null, min: null, max: null, total_count: 0 });
    const [cashflowRange, setCashflowRange] = useState(6);
    const [reportTrendView, setReportTrendView] = useState('trends'); // 'trends' | 'cashflow'

    const [modal, setModal] = useState(false);
    const [form, setForm] = useState({});
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [mode, setMode] = useState('login');
    const [auth, setAuth] = useState({ name: '', email: '', password: '' });
    const [mobile, setMobile] = useState(false);
    const [hidden, setHidden] = useState(false);
    const [filterKind, setFilterKind] = useState('All');
    const [filterCategory, setFilterCategory] = useState('All');
    const [search, setSearch] = useState('');

    // ── Light / Dark / System Theme (Clickable - no dropdown) ───────────────────
    const [theme, setTheme] = useState(() => {
        try {
            const saved = localStorage.getItem('moneta_theme');
            if (saved) return saved;
        } catch { }
        return 'system';
    });

    useEffect(() => {
        const applyTheme = t => {
            const isDark = t === 'dark' || (t === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
            // NOTE: only data-theme is used — never the `dark` class, which collides
            // with the legacy `.dark` button style and turns <html> into a flex box.
            document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
            document.documentElement.classList.remove('dark');
        };

        applyTheme(theme);
        try { localStorage.setItem('moneta_theme', theme); } catch { }

        if (theme === 'system') {
            const mq = window.matchMedia('(prefers-color-scheme: dark)');
            const handler = () => applyTheme('system');
            mq.addEventListener('change', handler);
            return () => mq.removeEventListener('change', handler);
        }
    }, [theme]);

    // ── Mobile drawer: lock the page, close on Escape ────────────────────────
    useEffect(() => {
        if (!mobile) return undefined;
        const previous = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        const onKeyDown = e => { if (e.key === 'Escape') setMobile(false); };
        window.addEventListener('keydown', onKeyDown);
        return () => {
            document.body.style.overflow = previous;
            window.removeEventListener('keydown', onKeyDown);
        };
    }, [mobile]);

    // ── Notes, Tasks & Journal live in ./life/store; badges read the same data ──
    const [notes] = useCollection(NOTES_KEY);
    const [tasks] = useCollection(TASKS_KEY);
    const [events] = useCollection(EVENTS_KEY);
    const pendingTasksCount = useMemo(() => tasks.filter(t => !t.done).length, [tasks]);

    // ── Global search: every record type, grouped by kind ───────────────────
    const searchResults = useMemo(() => {
        const q = search.trim().toLowerCase();
        if (!q) return [];
        const has = (...vals) => vals.some(v => String(v ?? '').toLowerCase().includes(q));
        const when = v => (v ? new Date(v).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) : '');
        const pageList = groups.flatMap(([, items]) => items);

        return [
            { id: 'pages', items: pageList.filter(p => p.toLowerCase().includes(q)).slice(0, 4).map(p => ({ id: p, title: p, subtitle: 'Go to page' })) },
            {
                id: 'transactions',
                items: tx.filter(t => has(t.description, t.category, t.payment_method, t.amount)).slice(0, 5).map(t => ({
                    id: t.id,
                    title: t.description || t.category,
                    subtitle: `${t.category} · ${t.payment_method}`,
                    meta: `${money(t.amount)} · ${when(t.txn_date)}`,
                })),
            },
            {
                id: 'notes',
                items: notes.filter(n => has(n.title, n.body, n.category, (n.tags || []).join(' '))).slice(0, 4).map(n => ({
                    id: n.id,
                    title: n.title || 'Untitled note',
                    subtitle: n.category,
                    meta: when(n.updatedAt || n.createdAt),
                })),
            },
            {
                id: 'tasks',
                items: tasks.filter(t => has(t.text, t.notes, t.category)).slice(0, 4).map(t => ({
                    id: t.id,
                    title: t.text,
                    subtitle: `${t.category}${t.due ? ` · due ${when(t.due)}` : ''}`,
                    meta: t.done ? 'Done' : '',
                })),
            },
            {
                id: 'journal',
                items: events.filter(e => has(e.title, e.notes, e.category)).slice(0, 4).map(e => ({
                    id: e.id,
                    title: e.title || 'Untitled entry',
                    subtitle: e.category,
                    meta: when(e.date),
                })),
            },
        ].filter(g => g.items.length);
    }, [search, tx, notes, tasks, events]);

    const pickSearchResult = useCallback(item => {
        if (!item) return;
        if (item.group === 'pages') { navigateTo(item.title); setSearch(''); return; }
        if (item.group === 'transactions') { setSearch(item.title); navigateTo('Transactions'); return; }
        if (item.group === 'notes') { navigateTo('Notes'); return; }
        if (item.group === 'tasks') { navigateTo('Tasks'); return; }
        if (item.group === 'journal') { navigateTo('Journal'); }
    }, [navigateTo]);

    // ── Dynamic Categories & Payment Methods Management ─────────────────────────
    const [expenseCats, setExpenseCats] = useState(() => {
        try {
            const saved = localStorage.getItem('moneta_expense_cats');
            if (saved) return JSON.parse(saved);
        } catch { }
        return DEFAULT_EXPENSE_CATS;
    });

    const [incomeCats, setIncomeCats] = useState(() => {
        try {
            const saved = localStorage.getItem('moneta_income_cats');
            if (saved) return JSON.parse(saved);
        } catch { }
        return DEFAULT_INCOME_CATS;
    });

    const [paymentMethods, setPaymentMethods] = useState(() => {
        try {
            const saved = localStorage.getItem('moneta_payment_methods');
            if (saved) {
                const parsed = JSON.parse(saved);
                return parsed.map(m => (m === 'UPI' ? 'SBI' : m));
            }
        } catch { }
        return DEFAULT_PAYMENT_METHODS;
    });

    const allCats = useMemo(() => Array.from(new Set([...expenseCats, ...incomeCats])).sort(), [expenseCats, incomeCats]);
    const [manageModal, setManageModal] = useState(null); // 'expense' | 'income' | 'payment' | null
    const [selectedCategoryDetail, setSelectedCategoryDetail] = useState(null); // category string for drilldown modal
    const [selectedPaymentDetail, setSelectedPaymentDetail] = useState(null); // payment method string for drilldown modal
    const [reportBreakdownTab, setReportBreakdownTab] = useState('category'); // 'category' | 'payment'

    // ── Category & Payment Wise Breakdown Analytics (with Average Metrics) ─────
    const categoryBreakdown = useMemo(() => {
        if (!analytics?.category_breakdown?.length) return [];
        const catTxCount = {};
        tx.filter(t => t.kind === 'expense').forEach(t => {
            catTxCount[t.category] = (catTxCount[t.category] || 0) + 1;
        });
        return analytics.category_breakdown.map(c => {
            const txns = c.txns ?? (catTxCount[c.category] || 1);
            const avg = c.avg ?? (txns ? Math.round(c.amount / txns) : c.amount);
            return { ...c, txns, avg };
        });
    }, [analytics, tx]);

    const paymentBreakdown = useMemo(() => {
        if (analytics?.payment_breakdown && analytics.payment_breakdown.length) {
            return analytics.payment_breakdown;
        }
        const expTotal = tx.filter(t => t.kind === 'expense').reduce((sum, t) => sum + Number(t.amount || 0), 0);
        const map = {};
        tx.forEach(t => {
            const pm = t.payment_method || 'Other';
            if (!map[pm]) map[pm] = { payment_method: pm, amount: 0, income: 0, txns: 0, exp_txns: 0, inc_txns: 0, pct: 0 };
            map[pm].txns += 1;
            if (t.kind === 'expense') {
                map[pm].amount += Number(t.amount || 0);
                map[pm].exp_txns += 1;
            } else if (t.kind === 'income') {
                map[pm].income += Number(t.amount || 0);
                map[pm].inc_txns += 1;
            }
        });
        return Object.values(map)
            .map(x => ({
                ...x,
                pct: expTotal ? Number(((x.amount / expTotal) * 100).toFixed(1)) : 0,
                net: x.income - x.amount,
                avg: x.exp_txns ? Math.round(x.amount / x.exp_txns) : (x.txns ? Math.round(x.amount / x.txns) : 0),
                avg_income: x.inc_txns ? Math.round(x.income / x.inc_txns) : 0,
                avg_overall: x.txns ? Math.round((x.amount + x.income) / x.txns) : 0,
            }))
            .sort((a, b) => b.amount - a.amount);
    }, [analytics, tx]);

    // ── Inline Transaction Addition state & handler ─────────────────────────────
    const amountInputRef = useRef(null);
    const [showInlineAdd, setShowInlineAdd] = useState(true);
    const [inlineTx, setInlineTx] = useState(() => ({
        kind: 'expense',
        amount: '',
        category: DEFAULT_EXPENSE_CATS[0] || 'Groceries',
        description: '',
        payment_method: DEFAULT_PAYMENT_METHODS[0] || 'SBI',
        txn_date: today(),
    }));
    const [inlineBusy, setInlineBusy] = useState(false);
    const [inlineError, setInlineError] = useState('');

    const handleSaveInlineTx = async e => {
        if (e) e.preventDefault();
        const amt = Number(inlineTx.amount);
        if (!inlineTx.amount || isNaN(amt) || amt <= 0) {
            setInlineError('Please enter a valid amount greater than 0');
            return;
        }
        setInlineBusy(true);
        setInlineError('');
        try {
            const payload = {
                kind: inlineTx.kind,
                amount: amt,
                category: inlineTx.category || (inlineTx.kind === 'income' ? incomeCats[0] : expenseCats[0]),
                description: inlineTx.description.trim() || inlineTx.category,
                payment_method: inlineTx.payment_method || paymentMethods[0] || 'SBI',
                txn_date: inlineTx.txn_date || today(),
            };
            await api.post('/transactions', payload);
            logActivity(`Added ${payload.kind} of ₹${payload.amount.toLocaleString('en-IN')} in ${payload.category}`, 'money');
            // Keep date, payment, category, kind for rapid entry; reset amount and description
            setInlineTx(prev => ({
                ...prev,
                amount: '',
                description: '',
            }));
            load();
            loadTxRange();
            loadCashflow();
            setTimeout(() => {
                amountInputRef.current?.focus();
            }, 60);
        } catch (err) {
            setInlineError(err.response?.data?.detail || 'Failed to save transaction');
        } finally {
            setInlineBusy(false);
        }
    };

    // ── Edit Transaction state & handlers ───────────────────────────────────────
    const [editingTx, setEditingTx] = useState(null);
    const [editBusy, setEditBusy] = useState(false);
    const [editError, setEditError] = useState('');

    const openEditTx = t => {
        setEditError('');
        setEditingTx({
            id: t.id,
            kind: t.kind || 'expense',
            amount: t.amount,
            category: t.category,
            description: t.description || '',
            payment_method: t.payment_method || (paymentMethods[0] || 'SBI'),
            txn_date: t.txn_date ? t.txn_date.slice(0, 10) : today(),
        });
    };

    const handleSaveEditTx = async e => {
        if (e) e.preventDefault();
        if (!editingTx) return;
        const amt = Number(editingTx.amount);
        if (!editingTx.amount || isNaN(amt) || amt <= 0) {
            setEditError('Please enter a valid amount greater than 0');
            return;
        }
        setEditBusy(true);
        setEditError('');
        try {
            const payload = {
                kind: editingTx.kind,
                amount: amt,
                category: editingTx.category,
                description: (editingTx.description || '').trim() || editingTx.category,
                payment_method: editingTx.payment_method,
                txn_date: editingTx.txn_date,
            };
            await api.put(`/transactions/${editingTx.id}`, payload);
            logActivity(`Updated ${payload.kind} of ₹${payload.amount.toLocaleString('en-IN')} in ${payload.category}`, 'money');
            setEditingTx(null);
            load();
            loadTxRange();
            loadCashflow();
        } catch (err) {
            setEditError(err.response?.data?.detail || 'Failed to update transaction');
        } finally {
            setEditBusy(false);
        }
    };

    useEffect(() => {
        try { localStorage.setItem('moneta_expense_cats', JSON.stringify(expenseCats)); } catch { }
    }, [expenseCats]);

    useEffect(() => {
        try { localStorage.setItem('moneta_income_cats', JSON.stringify(incomeCats)); } catch { }
    }, [incomeCats]);

    useEffect(() => {
        try { localStorage.setItem('moneta_payment_methods', JSON.stringify(paymentMethods)); } catch { }
    }, [paymentMethods]);

    const handleAddExpenseCat = name => {
        const trimmed = name.trim();
        if (!trimmed || expenseCats.includes(trimmed)) return;
        setExpenseCats(prev => [...prev, trimmed]);
        logActivity(`Added category: "${trimmed}" (Expense)`, 'system');
    };

    const handleRemoveExpenseCat = name => {
        setExpenseCats(prev => prev.filter(c => c !== name));
        logActivity(`Removed category: "${name}"`, 'system');
    };

    const handleAddIncomeCat = name => {
        const trimmed = name.trim();
        if (!trimmed || incomeCats.includes(trimmed)) return;
        setIncomeCats(prev => [...prev, trimmed]);
        logActivity(`Added category: "${trimmed}" (Income)`, 'system');
    };

    const handleRemoveIncomeCat = name => {
        setIncomeCats(prev => prev.filter(c => c !== name));
        logActivity(`Removed category: "${name}"`, 'system');
    };

    const handleAddPaymentMethod = name => {
        const trimmed = name.trim();
        if (!trimmed || paymentMethods.includes(trimmed)) return;
        setPaymentMethods(prev => [...prev, trimmed]);
        logActivity(`Added payment method: "${trimmed}"`, 'system');
    };

    const handleRemovePaymentMethod = name => {
        setPaymentMethods(prev => prev.filter(m => m !== name));
        logActivity(`Removed payment method: "${name}"`, 'system');
    };

    const handleResetDefaults = () => {
        if (confirm('Reset categories and payment methods to default?')) {
            setExpenseCats(DEFAULT_EXPENSE_CATS);
            setIncomeCats(DEFAULT_INCOME_CATS);
            setPaymentMethods(DEFAULT_PAYMENT_METHODS);
            logActivity('Reset categories & payment methods to defaults', 'system');
        }
    };

    useEffect(() => {
        const handleEsc = e => {
            if (e.key === 'Escape') {
                if (selectedCategoryDetail) setSelectedCategoryDetail(null);
                else if (manageModal) setManageModal(null);
            }
        };
        window.addEventListener('keydown', handleEsc);
        return () => window.removeEventListener('keydown', handleEsc);
    }, [manageModal, selectedCategoryDetail]);

    const api = useMemo(() => axios.create({ baseURL: API, headers: token ? { Authorization: `Bearer ${token}` } : {} }), [token]);

    const logout = () => {
        localStorage.removeItem('moneta_token');
        setToken('');
        setUser(null);
    };

    // ── Load transactions range summary
    const loadTxRange = useCallback(async () => {
        if (!token) return;
        try {
            const r = await api.get('/transactions/range');
            setTxRange(r.data);
        } catch { /* silent */ }
    }, [token, api]);

    // ── Main loader for Dashboard & Records based on current DateRange
    const load = useCallback(async () => {
        if (!token) return;
        try {
            const params = {};
            if (range.preset === 'all') {
                params.month = 'all';
            } else if (range.month) {
                params.month = range.month;
            } else if (range.startDate && range.endDate) {
                params.start_date = range.startDate;
                params.end_date = range.endDate;
            }

            const [dashRes, txRes, budgetRes, goalRes, invRes, liabRes] = await Promise.all([
                api.get('/dashboard', { params }),
                api.get('/transactions', { params }),
                api.get('/budgets', { params: range.month ? { month: range.month } : {} }),
                api.get('/goals'),
                api.get('/investments'),
                api.get('/liabilities'),
            ]);

            setD(dashRes.data);
            setTx(txRes.data);
            setBudgets(budgetRes.data);
            setGoals(goalRes.data);
            setInvestments(invRes.data);
            setLiabilities(liabRes.data);
        } catch (err) {
            if (err.response?.status === 401) logout();
            else setError(err.response?.data?.detail || 'Could not load data');
        }
    }, [token, range, api]);

    const loadCashflow = useCallback(async () => {
        if (!token) return;
        try {
            const r = await api.get('/cashflow', { params: { months: cashflowRange } });
            setCashflow(r.data);
        } catch { /* silent */ }
    }, [token, cashflowRange, api]);

    const loadAnalytics = useCallback(async () => {
        if (!token) return;
        try {
            const params = {};
            if (range.preset === 'all') {
                params.from = 'all';
            } else if (range.startDate && range.endDate) {
                params.start_date = range.startDate;
                params.end_date = range.endDate;
            } else if (range.month) {
                params.from = range.month;
                params.to = range.month;
            }
            const r = await api.get('/analytics', { params });
            setAnalytics(r.data);
        } catch { /* silent */ }
    }, [token, range, api]);

    useEffect(() => { load(); }, [load]);
    useEffect(() => { loadCashflow(); }, [loadCashflow]);
    useEffect(() => { if (page === 'Reports') loadAnalytics(); }, [page, loadAnalytics]);
    useEffect(() => {
        if (token) {
            loadTxRange();
            api.get('/auth/me').then(r => setUser(r.data)).catch(logout);
        }
    }, [token]);

    // The assistant writes through the API, so every view has to re-read after
    // it acts: money pages via their loaders, life pages via the sync event.
    const assistantChanged = useCallback(() => {
        load();
        loadCashflow();
        loadTxRange();
        if (page === 'Reports') loadAnalytics();
        try { window.dispatchEvent(new Event(REMOTE_CHANGE)); } catch { /* ignore */ }
    }, [load, loadCashflow, loadTxRange, loadAnalytics, page]);

    const authSubmit = async e => {
        e.preventDefault();
        setBusy(true);
        setError('');
        try {
            const r = await http.post('/auth/' + (mode === 'login' ? 'login' : 'register'), auth);
            localStorage.setItem('moneta_token', r.data.access_token);
            setToken(r.data.access_token);
            setUser(r.data.user);
        } catch (x) {
            setError(x.response?.data?.detail || 'Authentication failed');
        } finally {
            setBusy(false);
        }
    };

    const defaults = p => ({
        Transactions: { kind: 'expense', amount: '', category: expenseCats[0] || 'Groceries', description: '', payment_method: paymentMethods[0] || 'SBI', txn_date: today() },
        Budgets: { category: expenseCats[0] || 'Groceries', monthly_limit: '', month: thisMonthStr() },
        'Savings goals': { name: '', target_amount: '', saved_amount: '0', target_date: '' },
        Investments: { name: '', asset_type: 'Mutual Fund', invested_amount: '', current_value: '', notes: '' },
        Liabilities: { name: '', liability_type: 'Home Loan', outstanding_amount: '', monthly_emi: '0', notes: '' },
    }[p] || {});

    const add = () => {
        setError('');
        if (page === 'Transactions') {
            setShowInlineAdd(prev => !prev);
            return;
        }
        setForm(defaults(page));
        setModal(true);
    };

    const save = async e => {
        e.preventDefault();
        setBusy(true);
        setError('');
        let p = { ...form };
        ['amount', 'monthly_limit', 'target_amount', 'saved_amount', 'invested_amount', 'current_value', 'outstanding_amount', 'monthly_emi']
            .forEach(k => { if (p[k] !== undefined) p[k] = Number(p[k]); });
        if (p.target_date === '') p.target_date = null;
        const path = { Transactions: 'transactions', Budgets: 'budgets', 'Savings goals': 'goals', Investments: 'investments', Liabilities: 'liabilities' }[page];
        try {
            await api.post('/' + path, p);
            setModal(false);
            load();
            loadTxRange();
            if (page === 'Transactions') loadCashflow();
        } catch (x) {
            setError(x.response?.data?.detail || 'Unable to save');
        } finally {
            setBusy(false);
        }
    };

    const del = async (path, id) => {
        if (!confirm('Delete this record?')) return;
        try {
            await api.delete(`/${path}/${id}`);
            load();
            loadTxRange();
        } catch {
            setError('Delete failed');
        }
    };

    // ── Auth View ───────────────────────────────────────────────────────────────
    if (!token) return (
        <div className="auth">
            <div className="auth-left">
                <div className="brand">
                    <i className="brand-tile" aria-hidden="true"><span className="brand-glyph" /></i>
                    <div>
                        <b>Nirvaah</b>
                        <span className="brand-deva" lang="hi">निर्वाह</span>
                    </div>
                </div>
                <div>
                    <small>PERSONAL FINANCE, REIMAGINED</small>
                    <h1>A clearer picture.<br />A more confident you.</h1>
                    <p>Bring your everyday money, future plans and bigger goals into one considered view.</p>
                </div>
                <footer>YOUR MONEY, IN PERSPECTIVE</footer>
            </div>
            <form className="auth-form" onSubmit={authSubmit}>
                <small>WELCOME TO NIRVAAH</small>
                <h2>{mode === 'login' ? 'Welcome back' : 'Create your account'}</h2>
                <p>Sign in to see your financial picture.</p>
                {mode === 'register' && <label>Full name<input required value={auth.name} onChange={e => setAuth({ ...auth, name: e.target.value })} /></label>}
                <label>Email address<input type="email" required value={auth.email} onChange={e => setAuth({ ...auth, email: e.target.value })} /></label>
                <label>Password<input type="password" minLength="8" required value={auth.password} onChange={e => setAuth({ ...auth, password: e.target.value })} /></label>
                {error && <div className="error">{error}</div>}
                <button className="blue wide" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'} <ArrowUpRight size={16} /></button>
                <p className="switch">{mode === 'login' ? 'New to Nirvaah?' : 'Already registered?'} <button type="button" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>{mode === 'login' ? 'Create an account' : 'Sign in'}</button></p>
            </form>
        </div>
    );

    const data = d || { period: range.label, balance: 0, income: 0, expenses: 0, savings: 0, savings_rate: 0, investment_value: 0, liabilities: 0, net_worth: 0, category_expenses: [], budgets: [], recent_transactions: [], total_txns: 0 };

    // Expense trend, date by date, across the selected period. Empty days are
    // kept so the axis is continuous and a quiet week is visible as a gap.
    const expenseByDay = useMemo(() => {
        const start = range.startDate || txRange?.min_date;
        const end = range.endDate || txRange?.max_date;
        if (!start || !end || start > end) return [];
        const byDay = new Map();
        tx.forEach(t => {
            if (t.kind !== 'expense') return;
            const key = (t.txn_date || '').slice(0, 10);
            if (!key || key < start || key > end) return;
            byDay.set(key, (byDay.get(key) || 0) + Number(t.amount || 0));
        });
        const out = [];
        const cursor = new Date(`${start}T00:00:00`);
        const last = new Date(`${end}T00:00:00`);
        for (let i = 0; cursor <= last && i < 800; i++) {
            const key = `${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, '0')}-${String(cursor.getDate()).padStart(2, '0')}`;
            out.push({
                date: key,
                label: cursor.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }),
                shortLabel: cursor.toLocaleDateString('en-IN', { day: 'numeric' }),
                expense: Math.round((byDay.get(key) || 0) * 100) / 100,
            });
            cursor.setDate(cursor.getDate() + 1);
        }
        return out;
    }, [tx, range.startDate, range.endDate, txRange]);

    // Filtered transactions for Transactions view (supports description, category, payment method, date, and amount numbers)
    const filteredTx = tx.filter(t => {
        if (filterKind !== 'All' && t.kind !== filterKind.toLowerCase()) return false;
        if (filterCategory !== 'All' && t.category !== filterCategory) return false;
        if (search) {
            const rawQuery = search.toLowerCase().trim();
            // Cleaned query for numeric comparison (remove currency symbol, commas, minus, spaces)
            const cleanQuery = rawQuery.replace(/[₹,\s]/g, '');

            const desc = (t.description || '').toLowerCase();
            const cat = (t.category || '').toLowerCase();
            const pay = (t.payment_method || '').toLowerCase();
            const date = (t.date || '').toLowerCase();

            // Match text in description, category, payment method, or date
            const textMatch = `${desc} ${cat} ${pay} ${date}`.includes(rawQuery);

            // Amount matching: check raw amount, absolute amount, or formatted amount string
            const rawAmount = String(t.amount ?? '');
            const absAmount = String(Math.abs(Number(t.amount) || 0));
            const formattedAmount = money(t.amount).toLowerCase().replace(/[₹,\s]/g, '');

            const amountMatch = cleanQuery !== '' && (
                rawAmount.includes(cleanQuery) ||
                absAmount.includes(cleanQuery) ||
                formattedAmount.includes(cleanQuery)
            );

            return textMatch || amountMatch;
        }
        return true;
    });

    return (
        <>
        {busy && <div className="top-loader-bar" />}
        <div className="shell">
            {/* ── Sidebar ─────────────────────────────────────────────────────────── */}
            <aside className={`sidebar ${mobile ? 'show' : ''}`}>
                <div className="brand">
                    <i className="brand-tile" aria-hidden="true"><span className="brand-glyph" /></i>
                    <div><b>Nirvaah</b><small className="brand-line">Your livelihood, in focus.</small></div>
                    <button className="close" onClick={() => setMobile(false)}><X /></button>
                </div>
                <nav>
                    {groups.map(([g, items]) => (
                        <section key={g}>
                            <small>{g}</small>
                            {items.map(item => {
                                const I = icons[item];
                                return (
                                    <button
                                        key={item}
                                        className={page === item ? 'active' : ''}
                                        onClick={() => {
                                            navigateTo(item);
                                            setMobile(false);
                                        }}
                                    >
                                        <span className="nav-ico" style={{ '--page-tint': PAGE_TINTS[item] || 'var(--muted-foreground)' }}>
                                            <I size={17} />
                                        </span>
                                        {item === 'Assistant' ? 'Nirvaah AI' : item}
                                    </button>
                                );
                            })}
                        </section>
                    ))}
                </nav>
                <div className="profile">
                    <div className="avatar">{(user?.name || 'M')[0].toUpperCase()}</div>
                    <div><b>{user?.name || 'My account'}</b><small>{user?.email}</small></div>
                    <button onClick={logout} title="Sign out"><LogOut size={16} /></button>
                </div>
            </aside>
            {mobile && <div className="scrim" onClick={() => setMobile(false)} />}

            {/* ── Main Viewport ───────────────────────────────────────────────────── */}
            <main>
                <header>
                    <button className="hamb" onClick={() => setMobile(true)}><Menu /></button>

                    {/* Page heading sits beside the centred search */}
                    <div className="header-heading">
                        <div className="header-title" style={{ '--page-tint': PAGE_TINTS[page] || 'var(--foreground)' }}>
                            <span className="page-mark">
                                {(() => { const Mark = icons[page]; return Mark ? <Mark size={19} /> : null; })()}
                            </span>
                            <h1>{pageTitle(page)}</h1>
                        </div>
                        <p>
                            {pageSubtext(page)}
                            {page === 'Transactions' && (
                                <span className="heading-count">
                                    {filteredTx.length} {filteredTx.length === 1 ? 'record' : 'records'}
                                </span>
                            )}
                        </p>
                    </div>

                    {/* Floating search — searches every record type */}
                    <div className="topbar-search">
                        <GlobalSearch
                            query={search}
                            onQuery={setSearch}
                            groups={searchResults}
                            onPick={pickSearchResult}
                        />
                        <button
                            type="button"
                            className="theme-btn-single"
                            onClick={() => setTheme(prev => prev === 'light' ? 'dark' : prev === 'dark' ? 'system' : 'light')}
                            title={`Theme: ${theme.charAt(0).toUpperCase() + theme.slice(1)} (Click to toggle)`}
                            aria-label="Toggle color theme"
                        >
                            {theme === 'dark' ? <Moon size={16} /> : theme === 'light' ? <Sun size={16} /> : <Laptop size={16} />}
                        </button>
                    </div>

                    {/* Page actions, right of the search */}
                    <div className="header-slot header-actions">
                        {page !== 'Dashboard' && page !== 'Reports' && page !== 'Assistant'
                            && page !== 'Transactions' && !['Notes', 'Tasks', 'Journal'].includes(page) && (
                            <button className="blue" onClick={add}>
                                <Plus size={15} />
                                Add {singularPage(page)}
                            </button>
                        )}
                    </div>
                </header>

                <div className="content page-transition" key={page}>

                    {/* Dropdowns live in the body, under the header row */}
                    {['Dashboard', 'Reports', 'Budgets', 'Transactions'].includes(page) && (
                        <div className="page-filters">
                            <DateRangeFilter range={range} onChange={setRange} txRange={txRange} />
                            {page === 'Transactions' && (
                                <>
                                    <CustomSelect
                                        value={filterKind}
                                        onChange={setFilterKind}
                                        options={[
                                            { value: 'All', label: 'All types' },
                                            { value: 'Expense', label: 'Expenses only' },
                                            { value: 'Income', label: 'Income only' },
                                        ]}
                                        placeholder="Type"
                                    />
                                    <CustomSelect
                                        value={filterCategory}
                                        onChange={setFilterCategory}
                                        options={['All', ...allCats]}
                                        placeholder="Category"
                                        align="right"
                                    />
                                    <div className="filter-actions">
                                        <button
                                            type="button"
                                            className="soft tx-tag-btn"
                                            onClick={() => setManageModal('expense')}
                                            title="Add or remove categories & payment methods"
                                        >
                                            <SlidersHorizontal size={13} />
                                            <span>Manage Tags</span>
                                        </button>
                                        <button
                                            type="button"
                                            className={showInlineAdd ? 'soft tx-toggle-btn' : 'blue tx-toggle-btn'}
                                            onClick={() => setShowInlineAdd(prev => !prev)}
                                            title={showInlineAdd ? 'Close quick entry form' : 'Add transaction'}
                                        >
                                            <Plus size={14} style={{ transform: showInlineAdd ? 'rotate(45deg)' : 'none', transition: 'transform 0.2s ease' }} />
                                            <span>{showInlineAdd ? 'Close' : 'Quick add'}</span>
                                        </button>
                                        <button className="blue" onClick={add}>
                                            <Plus size={15} />
                                            Add transaction
                                        </button>
                                    </div>
                                </>
                            )}
                        </div>
                    )}
                    {error && <div className="error">{error}<button onClick={() => setError('')}>×</button></div>}

                    {/* ════════════════════════════════════════════════════════════════════
             PAGES: NOTES, TASKS, JOURNAL  (life pages - ./life/*)
             ════════════════════════════════════════════════════════════════════ */}
                    {page === 'Assistant' && (
                        <AssistantPage api={api} user={user} onChanged={assistantChanged} />
                    )}
                    {page === 'Notes' && <NotesPage />}
                    {page === 'Tasks' && <TasksPage />}
                    {page === 'Journal' && <JournalPage />}

                    {/* ════════════════════════════════════════════════════════════════════
             PAGE: DASHBOARD
             ════════════════════════════════════════════════════════════════════ */}
                    {page === 'Dashboard' && (
                        <div className="grid">
                            {/* Balance card */}
                            <article className="card balance">
                                <div className="card-head">
                                    <div className="label"><i className="ico blue-bg"><Wallet size={16} /></i>Net Balance</div>
                                    <span className="pill">{range.label}</span>
                                </div>
                                <div className="balance-line">
                                    <div className="balance-number">{hidden ? '₹ •••••••' : <AnimatedNumber value={data.savings} />}</div>
                                    <button className="eye" onClick={() => setHidden(!hidden)} aria-label={hidden ? 'Show amounts' : 'Hide amounts'}>{hidden ? <EyeOff size={16} /> : <Eye size={16} />}</button>
                                </div>
                                <div className="subline">
                                    <span className={data.savings >= 0 ? 'green' : 'red-text'}>
                                        {data.savings >= 0 ? '↗' : '↘'} {Math.abs(data.savings_rate)}%
                                    </span>
                                    savings rate <span className="muted">· Net cashflow ({data.total_txns} txns)</span>
                                </div>
                                <div className="actions">
                                    <button className="blue" onClick={() => { setShowInlineAdd(true); navigateTo('Transactions'); }}><Plus size={14} /> Add transaction</button>
                                    <button className="soft" onClick={() => navigateTo('Transactions')}><ArrowLeftRight size={14} /> View All Activity</button>
                                </div>
                            </article>

                            {/* Income card */}
                            <article className="card income">
                                <div className="card-head">
                                    <div className="label"><i className="round green-bg"><ArrowDownLeft size={17} /></i>Total Income</div>
                                    <span className="pill">{range.label}</span>
                                </div>
                                <strong className="big"><AnimatedNumber value={data.income} /></strong>
                                <span className="badge green-badge">Recorded in period</span>
                                <div className="split">
                                    <div>
                                        <small>Salary</small>
                                        <b>{money(tx.filter(t => t.kind === 'income' && t.category === 'Salary').reduce((a, t) => a + t.amount, 0))}</b>
                                    </div>
                                    <div>
                                        <small>Other income</small>
                                        <b>{money(tx.filter(t => t.kind === 'income' && t.category !== 'Salary').reduce((a, t) => a + t.amount, 0))}</b>
                                    </div>
                                </div>
                            </article>

                            {/* Expense card */}
                            <article className="card expense">
                                <div className="card-head">
                                    <div className="label"><i className="round red-bg"><ArrowUpRight size={17} /></i>Total Expense</div>
                                    <span className="pill">{range.label}</span>
                                </div>
                                <strong className="big"><AnimatedNumber value={data.expenses} /></strong>
                                <span className="badge red-badge">Recorded in period</span>
                                {data.budgets.length ? (
                                    <>
                                        <div className="meter">
                                            <i style={{
                                                width: `${Math.min(100, data.budgets.reduce((a, b) => a + b.spent, 0) / (data.budgets.reduce((a, b) => a + b.monthly_limit, 0) || 1) * 100)}%`
                                            }} />
                                        </div>
                                        <div className="meter-label">
                                            <span>Budget utilization</span>
                                            <b>{money(data.budgets.reduce((a, b) => a + b.monthly_limit - b.spent, 0))} left</b>
                                        </div>
                                    </>
                                ) : (
                                    <div className="meter-empty">
                                        <span>No budgets set</span>
                                        <button type="button" className="link" onClick={() => navigateTo('Budgets')}>Set a budget <ArrowUpRight size={12} /></button>
                                    </div>
                                )}
                            </article>

                            {/* Goals card */}
                            <article className={`card goals${goals.length ? '' : ' is-empty'}`}>
                                <div className="card-head">
                                    <div className="label"><i className="ico"><Target size={16} /></i>My goals</div>
                                    <button className="circle" onClick={() => navigateTo('Savings goals')}><Plus size={16} /></button>
                                </div>
                                <div className="goal-dark">
                                    {goals.length ? (
                                        <>
                                            <small>IN PROGRESS</small>
                                            <h3>{goals[0].name}</h3>
                                            <strong>{money(goals[0].saved_amount)}</strong>
                                            <p>of {money(goals[0].target_amount)} target</p>
                                            <div className="goal-meter"><i style={{ width: `${Math.min(100, goals[0].saved_amount / goals[0].target_amount * 100)}%` }} /></div>
                                            <small>{Math.round(goals[0].saved_amount / goals[0].target_amount * 100)}% completed</small>
                                        </>
                                    ) : (
                                        <>
                                            <small>MAKE A PLAN</small>
                                            <h3>Give your money a destination.</h3>
                                            <p>Create an emergency fund, holiday or other savings goal.</p>
                                            <button onClick={() => navigateTo('Savings goals')}>Explore goals <ArrowUpRight size={13} /></button>
                                        </>
                                    )}
                                </div>
                                {goals.slice(1, 3).map(g => (
                                    <div className="goal-row" key={g.id}>
                                        <span>{g.name}</span>
                                        <b>{Math.round(g.saved_amount / g.target_amount * 100)}%</b>
                                        <i><em style={{ width: `${Math.min(100, g.saved_amount / g.target_amount * 100)}%` }} /></i>
                                    </div>
                                ))}
                            </article>

                            {/* Cashflow chart */}
                            <article className="card cashflow">
                                <div className="card-head">
                                    <div className="label"><i className="ico"><ChartNoAxesCombined size={16} /></i>Cashflow trend</div>
                                    <SegmentedTabs
                                        ariaLabel="Cashflow range"
                                        value={cashflowRange}
                                        onChange={setCashflowRange}
                                        items={[3, 6, 12].map(n => ({ value: n, label: `${n}M` }))}
                                    />
                                </div>
                                <div className="legend">
                                    <span><i className="legend-blue" />Income</span>
                                    <span><i className="legend-lime" />Expense</span>
                                </div>
                                <div className="chart">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <BarChart data={cashflow} margin={{ top: 4, right: 4, left: -20, bottom: 0 }} barGap={3} barCategoryGap="30%">
                                            <CartesianGrid vertical={false} stroke="var(--chart-grid, #f0f0f0)" />
                                            <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fontSize: 13, fill: 'var(--muted-foreground)' }} />
                                            <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 13, fill: 'var(--muted-foreground)' }} tickFormatter={v => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v} />
                                            <Tooltip content={<ChartTooltip />} />
                                            <Bar dataKey="income" name="Income" fill="var(--chart-2)" radius={[4, 4, 0, 0]} maxBarSize={16} />
                                            <Bar dataKey="expense" name="Expense" fill="var(--chart-1)" radius={[4, 4, 0, 0]} maxBarSize={16} />
                                        </BarChart>
                                    </ResponsiveContainer>
                                </div>
                                <button className="link" onClick={() => navigateTo('Reports')}>View full financial report <ArrowUpRight size={13} /></button>
                            </article>

                            {/* Recent activity */}
                            <article className="card history">
                                <div className="card-head">
                                    <div className="label"><i className="ico"><RefreshCw size={15} /></i>Recent activity</div>
                                    <button className="dots" onClick={() => navigateTo('Transactions')}><MoreHorizontal /></button>
                                </div>
                                <div className="table-head"><span>DESCRIPTION</span><span>AMOUNT</span><span>METHOD</span></div>
                                {data.recent_transactions.length ? data.recent_transactions.slice(0, 5).map((t, i) => (
                                    <div className="mini-tx" key={t.id}>
                                        <div className="merchant">
                                            <i className={`merchant-icon m${i % 5}`}>{t.category.slice(0, 1)}</i>
                                            <span><b>{t.description || t.category}</b><small>{t.category}</small></span>
                                        </div>
                                        <b className={`mini-amount ${t.kind === 'income' ? 'green' : 'red-text'}`}>
                                            {t.kind === 'income' ? '+' : '−'}{money(t.amount)}
                                        </b>
                                        <div className="mini-method">
                                            <span className="pay-badge-colored" style={getPaymentStyle(t.payment_method)}>
                                                {t.payment_method}
                                            </span>
                                            <button
                                                type="button"
                                                className="icon-btn edit-btn mini-edit-btn"
                                                onClick={() => openEditTx(t)}
                                                title="Edit transaction"
                                            >
                                                <Pencil size={12} />
                                            </button>
                                        </div>
                                    </div>
                                )) : <div className="empty">
                                    <b>Nothing in this range</b>
                                    <span>Try a wider date range, or add a transaction.</span>
                                </div>}
                                <button className="link" onClick={() => navigateTo('Transactions')}>View all {txRange?.total_count || ''} transactions <ArrowUpRight size={13} /></button>
                            </article>

                            {/* Budget overview */}
                            <article className="card budget">
                                <div className="card-head">
                                    <div className="label"><i className="ico"><Wallet size={16} /></i>Budget overview</div>
                                    <button className="link" onClick={() => navigateTo('Budgets')}>Manage <ArrowUpRight size={12} /></button>
                                </div>
                                {data.budgets.length ? data.budgets.slice(0, 4).map(b => (
                                    <div className="budget-line" key={b.id}>
                                        <div><b>{b.category}</b><span>{money(b.spent)} <em>/ {money(b.monthly_limit)}</em></span></div>
                                        <i><em className={b.spent > b.monthly_limit ? 'over' : ''} style={{ width: Math.min(100, b.spent / b.monthly_limit * 100) + '%' }} /></i>
                                    </div>
                                )) : <div className="empty">Create category budgets to make spending more intentional.</div>}
                            </article>

                            {/* Report promo */}
                            <article className="card report">
                                <small>YOUR MONEY, IN PERSPECTIVE</small>
                                <h3>Financial<br />breakdown</h3>
                                <p>Analyze spending habits and monthly cashflow across any time range.</p>
                                <button onClick={() => navigateTo('Reports')}>View reports <ArrowUpRight size={14} /></button>
                            </article>

                            {/* Financial position */}
                            <article className="card networth">
                                <div className="card-head">
                                    <div className="label"><i className="ico"><Landmark size={16} /></i>Financial position</div>
                                    <span className="pill">OVERVIEW</span>
                                </div>
                                <small>ESTIMATED NET WORTH</small>
                                <strong><AnimatedNumber value={data.net_worth} /></strong>
                                <div className="net-detail">
                                    <span>Investments <b>{money(data.investment_value)}</b></span>
                                    <span>Liabilities <b>{money(data.liabilities)}</b></span>
                                </div>
                                <button className="link" onClick={() => navigateTo('Reports')}>See breakdown <ArrowUpRight size={13} /></button>
                            </article>
                        </div>
                    )}

                    {/* ════════════════════════════════════════════════════════════════════
             PAGE: TRANSACTIONS
             ════════════════════════════════════════════════════════════════════ */}
                    {page === 'Transactions' && (
                        <section className="panel transactions-panel">
                            {/* ── Frozen Top Controls Bar (Never scrolls, always on top) ── */}
                            <div className="transactions-frozen-header">
                                {/* ── Ultra-Minimal Compact Inline Quick Entry ── */}
                                {showInlineAdd && (
                                    <div className="inline-add-compact-wrap">
                                        <form
                                            className="inline-tx-form-compact"
                                            onSubmit={handleSaveInlineTx}
                                            onKeyDown={e => {
                                                if (e.altKey && (e.key === 'e' || e.key === 'E')) {
                                                    e.preventDefault();
                                                    setInlineTx(prev => ({
                                                        ...prev,
                                                        kind: 'expense',
                                                        category: expenseCats.includes(prev.category) ? prev.category : (expenseCats[0] || 'Groceries')
                                                    }));
                                                } else if (e.altKey && (e.key === 'i' || e.key === 'I')) {
                                                    e.preventDefault();
                                                    setInlineTx(prev => ({
                                                        ...prev,
                                                        kind: 'income',
                                                        category: incomeCats.includes(prev.category) ? prev.category : (incomeCats[0] || 'Salary')
                                                    }));
                                                }
                                            }}
                                        >
                                            <button
                                                type="button"
                                                className={`min-type-btn ${inlineTx.kind === 'expense' ? 'is-exp' : 'is-inc'}`}
                                                onClick={() => setInlineTx(prev => {
                                                    const kind = prev.kind === 'expense' ? 'income' : 'expense';
                                                    const pool = kind === 'expense' ? expenseCats : incomeCats;
                                                    return {
                                                        ...prev,
                                                        kind,
                                                        category: pool.includes(prev.category) ? prev.category : (pool[0] || ''),
                                                    };
                                                })}
                                                title="Toggle expense / income (Alt+E / Alt+I)"
                                            >
                                                {inlineTx.kind === 'expense' ? <ArrowUpRight size={13} /> : <ArrowDownLeft size={13} />}
                                                <span>{inlineTx.kind === 'expense' ? 'Expense' : 'Income'}</span>
                                            </button>

                                            <div className="min-field field-amount">
                                                <span className="min-curr">₹</span>
                                                <input
                                                    ref={amountInputRef}
                                                    type="number"
                                                    step="any"
                                                    min="0.01"
                                                    placeholder="0.00"
                                                    value={inlineTx.amount}
                                                    onChange={e => setInlineTx(prev => ({ ...prev, amount: e.target.value }))}
                                                    required
                                                />
                                            </div>

                                            <div className="min-field field-category">
                                                <CustomSelect
                                                    value={inlineTx.category}
                                                    onChange={val => setInlineTx(prev => ({ ...prev, category: val }))}
                                                    options={inlineTx.kind === 'income' ? incomeCats : expenseCats}
                                                    placeholder="Category"
                                                    fullWidth
                                                />
                                            </div>

                                            <div className="min-field field-desc">
                                                <input
                                                    type="text"
                                                    placeholder="Description (optional)…"
                                                    value={inlineTx.description}
                                                    onChange={e => setInlineTx(prev => ({ ...prev, description: e.target.value }))}
                                                />
                                            </div>

                                            <div className="min-field field-payment">
                                                <CustomSelect
                                                    value={inlineTx.payment_method}
                                                    onChange={val => setInlineTx(prev => ({ ...prev, payment_method: val }))}
                                                    options={paymentMethods}
                                                    placeholder="Payment"
                                                    fullWidth
                                                />
                                            </div>

                                            <div className="min-field field-date">
                                                <input
                                                    type="date"
                                                    value={inlineTx.txn_date}
                                                    title="Press 'T' for Today, 'Y' for Yesterday"
                                                    onChange={e => setInlineTx(prev => ({ ...prev, txn_date: e.target.value }))}
                                                    onKeyDown={e => {
                                                        if (e.key === 't' || e.key === 'T') {
                                                            e.preventDefault();
                                                            setInlineTx(prev => ({ ...prev, txn_date: today() }));
                                                        } else if (e.key === 'y' || e.key === 'Y') {
                                                            e.preventDefault();
                                                            setInlineTx(prev => ({ ...prev, txn_date: yesterday() }));
                                                        } else if (e.key === '+' || e.key === '=') {
                                                            e.preventDefault();
                                                            setInlineTx(prev => {
                                                                const d = new Date(prev.txn_date || today());
                                                                d.setDate(d.getDate() + 1);
                                                                return { ...prev, txn_date: d.toISOString().slice(0, 10) };
                                                            });
                                                        } else if (e.key === '-' || e.key === '_') {
                                                            e.preventDefault();
                                                            setInlineTx(prev => {
                                                                const d = new Date(prev.txn_date || today());
                                                                d.setDate(d.getDate() - 1);
                                                                return { ...prev, txn_date: d.toISOString().slice(0, 10) };
                                                            });
                                                        }
                                                    }}
                                                    required
                                                />
                                            </div>

                                            <button
                                                type="submit"
                                                className="blue min-save-btn"
                                                disabled={inlineBusy || !inlineTx.amount}
                                                title="Save record (Enter)"
                                            >
                                                <Plus size={14} />
                                                <span>{inlineBusy ? '…' : 'Save'}</span>
                                            </button>
                                        </form>

                                        {inlineError && <div className="inline-tx-error compact-error">{inlineError}</div>}
                                    </div>
                                )}
                            </div>

                            {/* ── Dedicated Scroll Container: only this scrolls! ── */}
                            <div className="transactions-scroll-container">
                                <table>
                                    <thead>
                                        <tr>
                                            <th>Description</th>
                                            <th>Category</th>
                                            <th>Date</th>
                                            <th>Payment</th>
                                            <th>Amount</th>
                                            <th></th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {filteredTx.length ? filteredTx.map(t => (
                                            <tr key={t.id}>
                                                <td><b>{t.description || t.category}</b></td>
                                                <td>
                                                    <span className="cat-badge-colored" style={getCategoryStyle(t.category)}>
                                                        {t.category}
                                                    </span>
                                                </td>
                                                <td>{new Date(t.txn_date + 'T00:00:00').toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}</td>
                                                <td>
                                                    <span className="pay-badge-colored" style={getPaymentStyle(t.payment_method)}>
                                                        {t.payment_method}
                                                    </span>
                                                </td>
                                                <td>
                                                    <b className={t.kind === 'income' ? 'green' : 'red-text'}>
                                                        {t.kind === 'income' ? '+' : '−'}{money(t.amount)}
                                                    </b>
                                                </td>
                                                <td>
                                                    <div className="row-actions">
                                                        <button
                                                            type="button"
                                                            className="icon-btn edit-btn"
                                                            onClick={() => openEditTx(t)}
                                                            title="Edit record"
                                                        >
                                                            <Pencil size={13} />
                                                        </button>
                                                        <button
                                                            type="button"
                                                            className="icon-btn delete-btn"
                                                            onClick={() => del('transactions', t.id)}
                                                            title="Delete record"
                                                        >
                                                            <Trash2 size={13} />
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        )) : (
                                            <tr>
                                                <td colSpan={6}>
                                                    <div className="empty">
                                                        <b>No transactions here</b>
                                                        <span>Nothing matches this filter and date range. Try widening the range or clearing the category.</span>
                                                    </div>
                                                </td>
                                            </tr>
                                        )}
                                    </tbody>
                                </table>
                            </div>
                        </section>
                    )}

                    {/* ════════════════════════════════════════════════════════════════════
             PAGE: BUDGETS
             ════════════════════════════════════════════════════════════════════ */}
                    {page === 'Budgets' && (
                        <section className="panel">
                            <div className="table-wrap">
                                <table>
                                    <thead>
                                        <tr>
                                            <th style={{ width: '24%' }}>Category</th>
                                            <th style={{ width: '14%' }}>Month</th>
                                            <th style={{ width: '15%', textAlign: 'right' }}>Limit</th>
                                            <th style={{ width: '15%', textAlign: 'right' }}>Spent</th>
                                            <th style={{ width: '20%' }}>Progress</th>
                                            <th style={{ width: '12%', textAlign: 'right' }}>Left</th>
                                            <th style={{ width: '84px' }}></th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {budgets.length ? budgets.map(b => {
                                            const pct = Math.min(100, Math.round((b.spent / (b.monthly_limit || 1)) * 100));
                                            return (
                                                <tr key={b.id}>
                                                    <td><span className="cat-badge-colored" style={getCategoryStyle(b.category)}>{b.category}</span></td>
                                                    <td className="muted">{monthLabel(b.month)}</td>
                                                    <td className="num">{money(b.monthly_limit)}</td>
                                                    <td className="num">{money(b.spent)}</td>
                                                    <td>
                                                        <div className="table-progress">
                                                            <div className="table-progress-track"><i style={{ width: `${pct}%` }} /></div>
                                                            <span>{pct}%</span>
                                                        </div>
                                                    </td>
                                                    <td className="num">{money(b.remaining)}</td>
                                                    <td>
                                                        <button className="icon-btn" onClick={() => del('budgets', b.id)} title="Delete budget"><Trash2 size={14} /></button>
                                                    </td>
                                                </tr>
                                            );
                                        }) : (
                                            <tr>
                                                <td colSpan={7}>
                                                    <div className="empty">
                                                        <b>No budgets yet</b>
                                                        <span>Set a monthly limit per category to make spending intentional.</span>
                                                    </div>
                                                </td>
                                            </tr>
                                        )}
                                    </tbody>
                                </table>
                            </div>
                        </section>
                    )}

                    {/* ════════════════════════════════════════════════════════════════════
             PAGE: SAVINGS GOALS
             ════════════════════════════════════════════════════════════════════ */}
                    {page === 'Savings goals' && (
                        <section className="panel">
                            <h2 style={{ marginBottom: 4 }}>Savings goals</h2>
                            <p className="muted" style={{ marginBottom: 20 }}>What you are setting money aside for, and how close you are.</p>
                            <div className="table-wrap">
                                <table>
                                    <thead><tr><th>Goal</th><th>Target</th><th>Saved</th><th>Progress</th><th>Target date</th><th></th></tr></thead>
                                    <tbody>
                                        {goals.length ? goals.map(g => {
                                            const pct = Math.min(100, Math.round((g.saved_amount / (g.target_amount || 1)) * 100));
                                            return (
                                                <tr key={g.id}>
                                                    <td><b>{g.name}</b></td>
                                                    <td>{money(g.target_amount)}</td>
                                                    <td><b>{money(g.saved_amount)}</b></td>
                                                    <td>
                                                        <div className="table-progress">
                                                            <div className="table-progress-track"><i style={{ width: `${pct}%` }} /></div>
                                                            <span>{pct}%</span>
                                                        </div>
                                                    </td>
                                                    <td>{g.target_date || '—'}</td>
                                                    <td><button className="icon-btn" onClick={() => del('goals', g.id)} title="Delete goal"><Trash2 size={14} /></button></td>
                                                </tr>
                                            );
                                        }) : <tr><td colSpan={6}>
                                            <div className="empty">
                                                <b>No savings goals yet</b>
                                                <span>Give your money a destination — an emergency fund, a trip, a big purchase.</span>
                                            </div>
                                        </td></tr>}
                                    </tbody>
                                </table>
                            </div>
                        </section>
                    )}

                    {/* ════════════════════════════════════════════════════════════════════
             PAGE: INVESTMENTS
             ════════════════════════════════════════════════════════════════════ */}
                    {page === 'Investments' && (
                        <section className="panel">
                            <h2 style={{ marginBottom: 4 }}>Investment portfolio</h2>
                            <p className="muted" style={{ marginBottom: 20 }}>Manually tracked values · not live market prices.</p>
                            <div className="table-wrap">
                                <table>
                                    <thead><tr><th>Investment</th><th>Asset type</th><th>Invested</th><th>Current value</th><th>Gain / Loss</th><th></th></tr></thead>
                                    <tbody>
                                        {investments.length ? investments.map(x => (
                                            <tr key={x.id}>
                                                <td><b>{x.name}</b></td>
                                                <td><span className="cat-badge">{x.asset_type}</span></td>
                                                <td>{money(x.invested_amount)}</td>
                                                <td>{money(x.current_value)}</td>
                                                <td>
                                                    <b className={x.current_value >= x.invested_amount ? 'green' : 'red-text'}>
                                                        {x.current_value >= x.invested_amount ? '+' : ''}{money(x.current_value - x.invested_amount)}
                                                    </b>
                                                </td>
                                                <td><button className="icon-btn" onClick={() => del('investments', x.id)}><Trash2 size={14} /></button></td>
                                            </tr>
                                        )) : <tr><td colSpan={6}>
                                            <div className="empty">
                                                <b>No investments recorded yet</b>
                                                <span>Add holdings manually to track what you own and what it cost.</span>
                                            </div>
                                        </td></tr>}
                                    </tbody>
                                </table>
                            </div>
                        </section>
                    )}

                    {/* ════════════════════════════════════════════════════════════════════
             PAGE: LIABILITIES
             ════════════════════════════════════════════════════════════════════ */}
                    {page === 'Liabilities' && (
                        <section className="panel">
                            <h2 style={{ marginBottom: 4 }}>Loans &amp; liabilities</h2>
                            <p className="muted" style={{ marginBottom: 20 }}>Outstanding balances and monthly EMIs.</p>
                            <div className="table-wrap">
                                <table>
                                    <thead><tr><th>Name</th><th>Type</th><th>Outstanding</th><th>Monthly EMI</th><th></th></tr></thead>
                                    <tbody>
                                        {liabilities.length ? liabilities.map(x => (
                                            <tr key={x.id}>
                                                <td><b>{x.name}</b></td>
                                                <td><span className="cat-badge">{x.liability_type}</span></td>
                                                <td><b className="red-text">{money(x.outstanding_amount)}</b></td>
                                                <td>{money(x.monthly_emi)}</td>
                                                <td><button className="icon-btn" onClick={() => del('liabilities', x.id)}><Trash2 size={14} /></button></td>
                                            </tr>
                                        )) : <tr><td colSpan={5}>
                                            <div className="empty">
                                                <b>No liabilities recorded yet</b>
                                                <span>Add loans and credit lines to see what you still owe.</span>
                                            </div>
                                        </td></tr>}
                                    </tbody>
                                </table>
                            </div>
                        </section>
                    )}

                    {/* ════════════════════════════════════════════════════════════════════
             PAGE: REPORTS
             ════════════════════════════════════════════════════════════════════ */}
                    {page === 'Reports' && (
                        <div className="reports-layout">
                            <section className="panel report-controls">
                                <div className="report-ctrl-row">
                                    <div>
                                        <small>FINANCIAL ANALYSIS</small>
                                        <h2>Performance &amp; Breakdown</h2>
                                    </div>
                                </div>

                                {analytics && (
                                    <div className="report-summary">
                                        <div className="summary-stat">
                                            <small>TOTAL INCOME</small>
                                            <b className="green"><AnimatedNumber value={analytics.total_income} /></b>
                                        </div>
                                        <div className="summary-stat">
                                            <small>TOTAL EXPENSE</small>
                                            <b className="red-text"><AnimatedNumber value={analytics.total_expense} /></b>
                                        </div>
                                        <div className="summary-stat">
                                            <small>NET SAVINGS</small>
                                            <b className={analytics.total_income - analytics.total_expense >= 0 ? 'green' : 'red-text'}>
                                                <AnimatedNumber value={analytics.total_income - analytics.total_expense} />
                                            </b>
                                        </div>
                                        <div className="summary-stat">
                                            <small>SAVINGS RATE</small>
                                            <b>
                                                {analytics.total_income
                                                    ? (((analytics.total_income - analytics.total_expense) / analytics.total_income) * 100).toFixed(1)
                                                    : 0}%
                                            </b>
                                        </div>
                                        <div className="summary-stat">
                                            <small>AVG EXPENSE / TXN</small>
                                            <b className="red-text">
                                                {money(analytics.avg_expense_per_txn ?? (tx.filter(t => t.kind === 'expense').length ? Math.round(analytics.total_expense / tx.filter(t => t.kind === 'expense').length) : 0))}
                                            </b>
                                        </div>
                                        <div className="summary-stat">
                                            <small>AVG INCOME / TXN</small>
                                            <b className="green">
                                                {money(analytics.avg_income_per_txn ?? (tx.filter(t => t.kind === 'income').length ? Math.round(analytics.total_income / tx.filter(t => t.kind === 'income').length) : 0))}
                                            </b>
                                        </div>
                                    </div>
                                )}
                            </section>

                            <div className="reports-grid">

                                {/* ── ROW 1: Unified Cashflow & Trends Hero Chart with Toggle ── */}
                                <section className="panel report-chart-panel report-trend-full">
                                    <div className="card-head" style={{ flexWrap: 'wrap', gap: 12 }}>
                                        <SegmentedTabs
                                            ariaLabel="Report view"
                                            value={reportTrendView}
                                            onChange={setReportTrendView}
                                            items={[
                                                { value: 'trends', label: 'Income & Expense Trends', icon: <TrendingUp size={14} /> },
                                                { value: 'cashflow', label: 'Monthly Cashflow', icon: <ChartNoAxesCombined size={14} /> },
                                                { value: 'expense', label: 'Expense Trend', icon: <ArrowUpRight size={14} /> },
                                            ]}
                                        />

                                        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                                            <div className="legend" style={{ margin: 0 }}>
                                                {reportTrendView !== 'expense' && (
                                                    <span><i className={reportTrendView === 'trends' ? 'legend-income-line' : 'legend-blue'} />Income</span>
                                                )}
                                                <span><i className={reportTrendView === 'trends' ? 'legend-expense-line' : 'legend-lime'} />Expense</span>
                                                {reportTrendView === 'expense' && expenseByDay.length > 0 && (
                                                    <span className="legend-total">
                                                        Total {money(expenseByDay.reduce((sum, d) => sum + d.expense, 0))}
                                                        <i>·</i>
                                                        {money(Math.round(expenseByDay.reduce((sum, d) => sum + d.expense, 0) / expenseByDay.length))}/day
                                                    </span>
                                                )}
                                            </div>
                                            <SegmentedTabs
                                                ariaLabel="Cashflow range"
                                                value={cashflowRange}
                                                onChange={setCashflowRange}
                                                items={[3, 6, 12].map(n => ({ value: n, label: `${n}M` }))}
                                            />
                                        </div>
                                    </div>
                                    {cashflow?.length ? (() => {
                                        const hasData = cashflow.some(d => d.income > 0 || d.expense > 0);
                                        if (!hasData) return <div className="empty">No cashflow data for this period.</div>;
                                        const maxVal = Math.max(...cashflow.map(d => Math.max(d.income, d.expense)));
                                        const trendTooltip = ({ active, payload, label }) => {
                                            if (!active || !payload?.length) return null;
                                            return (
                                                <div className="chart-tip">
                                                    <div className="tip-label">{label}</div>
                                                    {payload.map(p => (
                                                        <div key={p.dataKey} className="tip-row" style={{ color: p.color || (p.dataKey === 'income' ? 'var(--chart-2)' : (reportTrendView === 'trends' ? 'var(--chart-1)' : 'var(--chart-1)')) }}>
                                                            <span>{p.name}</span>
                                                            <b>{money(p.value)}</b>
                                                        </div>
                                                    ))}
                                                    {payload.length === 2 && (
                                                        <div className="tip-row" style={{ color: payload[0].value >= payload[1].value ? 'var(--chart-2)' : 'var(--chart-1)', borderTop: '1px solid var(--border)', paddingTop: 4, marginTop: 4 }}>
                                                            <span>Net</span>
                                                            <b>{payload[0].value >= payload[1].value ? '+' : '−'}{money(Math.abs(payload[0].value - payload[1].value))}</b>
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        };
                                        return (
                                            <div style={{ height: 260, marginTop: 12 }}>
                                                <ResponsiveContainer width="100%" height="100%">
                                                    {reportTrendView === 'trends' ? (
                                                        <AreaChart data={cashflow} margin={{ top: 10, right: 20, left: -10, bottom: 0 }}>
                                                            <defs>
                                                                <linearGradient id="incomeGrad" x1="0" y1="0" x2="0" y2="1">
                                                                    <stop offset="5%" stopColor="var(--chart-2)" stopOpacity={0.18} />
                                                                    <stop offset="95%" stopColor="var(--chart-2)" stopOpacity={0.01} />
                                                                </linearGradient>
                                                                <linearGradient id="expenseGrad" x1="0" y1="0" x2="0" y2="1">
                                                                    <stop offset="5%" stopColor="var(--chart-1)" stopOpacity={0.15} />
                                                                    <stop offset="95%" stopColor="var(--chart-1)" stopOpacity={0.01} />
                                                                </linearGradient>
                                                            </defs>
                                                            <CartesianGrid vertical={false} stroke="var(--chart-grid, #f0f0f0)" />
                                                            <XAxis
                                                                dataKey="label"
                                                                axisLine={false}
                                                                tickLine={false}
                                                                tick={{ fontSize: 13, fill: 'var(--muted-foreground)' }}
                                                            />
                                                            <YAxis
                                                                axisLine={false}
                                                                tickLine={false}
                                                                tick={{ fontSize: 13, fill: 'var(--muted-foreground)' }}
                                                                tickFormatter={v => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}
                                                                domain={[0, Math.ceil(maxVal * 1.1)]}
                                                            />
                                                            <Tooltip content={trendTooltip} />
                                                            <ReferenceLine y={0} stroke="var(--border)" strokeDasharray="3 3" />
                                                            <Area
                                                                type="monotone"
                                                                dataKey="income"
                                                                name="Income"
                                                                stroke="var(--chart-2)"
                                                                strokeWidth={2.5}
                                                                fill="url(#incomeGrad)"
                                                                dot={{ r: 3.5, fill: 'var(--chart-2)', strokeWidth: 0 }}
                                                                activeDot={{ r: 5.5, fill: 'var(--chart-2)', stroke: 'var(--card)', strokeWidth: 2 }}
                                                            />
                                                            <Area
                                                                type="monotone"
                                                                dataKey="expense"
                                                                name="Expense"
                                                                stroke="var(--chart-1)"
                                                                strokeWidth={2.5}
                                                                fill="url(#expenseGrad)"
                                                                dot={{ r: 3.5, fill: 'var(--chart-1)', strokeWidth: 0 }}
                                                                activeDot={{ r: 5.5, fill: 'var(--chart-1)', stroke: 'var(--card)', strokeWidth: 2 }}
                                                            />
                                                        </AreaChart>
                                                    ) : reportTrendView === 'expense' ? (
                                                        expenseByDay.length <= 62 ? (
                                                            <BarChart data={expenseByDay} margin={{ top: 18, right: 16, left: -10, bottom: 0 }} barCategoryGap="26%">
                                                                <CartesianGrid vertical={false} stroke="var(--chart-grid, #f0f0f0)" />
                                                                <XAxis
                                                                    dataKey="label"
                                                                    axisLine={false}
                                                                    tickLine={false}
                                                                    interval="preserveStartEnd"
                                                                    minTickGap={18}
                                                                    tick={{ fontSize: 12, fill: 'var(--muted-foreground)' }}
                                                                />
                                                                <YAxis
                                                                    axisLine={false}
                                                                    tickLine={false}
                                                                    tick={{ fontSize: 13, fill: 'var(--muted-foreground)' }}
                                                                    tickFormatter={v => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}
                                                                    domain={[0, Math.ceil(Math.max(...expenseByDay.map(d => d.expense), 1) * 1.15)]}
                                                                />
                                                                <Tooltip content={trendTooltip} />
                                                                <Bar dataKey="expense" name="Expense" fill="var(--chart-1)" radius={[4, 4, 0, 0]} maxBarSize={22}>
                                                                    <LabelList
                                                                        dataKey="expense"
                                                                        position="top"
                                                                        formatter={v => (v > 0 ? (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v) : '')}
                                                                        fill="var(--muted-foreground)"
                                                                        fontSize={11}
                                                                    />
                                                                </Bar>
                                                            </BarChart>
                                                        ) : (
                                                            <AreaChart data={expenseByDay} margin={{ top: 14, right: 16, left: -10, bottom: 0 }}>
                                                                <defs>
                                                                    <linearGradient id="dailyExpenseGrad" x1="0" y1="0" x2="0" y2="1">
                                                                        <stop offset="5%" stopColor="var(--chart-1)" stopOpacity={0.22} />
                                                                        <stop offset="95%" stopColor="var(--chart-1)" stopOpacity={0.01} />
                                                                    </linearGradient>
                                                                </defs>
                                                                <CartesianGrid vertical={false} stroke="var(--chart-grid, #f0f0f0)" />
                                                                <XAxis
                                                                    dataKey="label"
                                                                    axisLine={false}
                                                                    tickLine={false}
                                                                    interval="preserveStartEnd"
                                                                    minTickGap={28}
                                                                    tick={{ fontSize: 12, fill: 'var(--muted-foreground)' }}
                                                                />
                                                                <YAxis
                                                                    axisLine={false}
                                                                    tickLine={false}
                                                                    tick={{ fontSize: 13, fill: 'var(--muted-foreground)' }}
                                                                    tickFormatter={v => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}
                                                                    domain={[0, Math.ceil(Math.max(...expenseByDay.map(d => d.expense), 1) * 1.15)]}
                                                                />
                                                                <Tooltip content={trendTooltip} />
                                                                <Area
                                                                    type="monotone"
                                                                    dataKey="expense"
                                                                    name="Expense"
                                                                    stroke="var(--chart-1)"
                                                                    strokeWidth={2}
                                                                    fill="url(#dailyExpenseGrad)"
                                                                    dot={false}
                                                                    activeDot={{ r: 4.5, fill: 'var(--chart-1)', stroke: 'var(--card)', strokeWidth: 2 }}
                                                                />
                                                            </AreaChart>
                                                        )
                                                    ) : (
                                                        <BarChart data={cashflow} margin={{ top: 10, right: 20, left: -10, bottom: 0 }} barGap={6} barCategoryGap="28%">
                                                            <CartesianGrid vertical={false} stroke="var(--chart-grid, #f0f0f0)" />
                                                            <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fontSize: 13, fill: 'var(--muted-foreground)' }} />
                                                            <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 13, fill: 'var(--muted-foreground)' }} tickFormatter={v => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v} />
                                                            <Tooltip content={trendTooltip} />
                                                            <Bar dataKey="income" name="Income" fill="var(--chart-2)" radius={[4, 4, 0, 0]} maxBarSize={16} />
                                                            <Bar dataKey="expense" name="Expense" fill="var(--chart-1)" radius={[4, 4, 0, 0]} maxBarSize={16} />
                                                        </BarChart>
                                                    )}
                                                </ResponsiveContainer>
                                            </div>
                                        );
                                    })() : <div className="empty">No cashflow data available.</div>}

                                    {/* Month-by-month stats strip */}
                                    {cashflow?.some(d => d.income > 0 || d.expense > 0) && (
                                        <div className="trend-month-strip">
                                            {cashflow.filter(d => d.income > 0 || d.expense > 0).map(d => {
                                                const net = d.income - d.expense;
                                                return (
                                                    <div key={d.month} className="trend-month-cell">
                                                        <span className="tmc-label">{d.label}</span>
                                                        <span className="tmc-income">↑ {money(d.income)}</span>
                                                        <span className="tmc-expense">↓ {money(d.expense)}</span>
                                                        <span className={`tmc-net ${net >= 0 ? 'pos' : 'neg'}`}>
                                                            {net >= 0 ? '+' : '−'}{money(Math.abs(net))}
                                                        </span>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    )}
                                </section>

                                {/* ── ROW 2: Expense by Category | Spends by Payment Method ── */}

                                {/* Expense by Category Pie Chart */}
                                <section className="panel report-chart-panel">
                                    <div className="card-head">
                                        <div className="label"><i className="ico"><TrendingDown size={16} /></i>Expense by Category</div>
                                        <span className="pill">{range.label}</span>
                                    </div>
                                    {categoryBreakdown?.length ? (
                                        <>
                                            <div style={{ height: 230, marginTop: 8 }}>
                                                <ResponsiveContainer width="100%" height="100%">
                                                    <PieChart>
                                                        <Pie
                                                            data={categoryBreakdown.slice(0, 10)}
                                                            dataKey="amount"
                                                            nameKey="category"
                                                            innerRadius={60}
                                                            outerRadius={95}
                                                            paddingAngle={2}
                                                            stroke="var(--card)"
                                                            strokeWidth={2}
                                                            onClick={entry => {
                                                                if (entry?.category) setSelectedCategoryDetail(entry.category);
                                                            }}
                                                            style={{ cursor: 'pointer' }}
                                                        >
                                                            {categoryBreakdown.slice(0, 10).map((x, i) => (
                                                                <Cell key={x.category} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                                                            ))}
                                                        </Pie>
                                                        <Tooltip
                                                            formatter={(val, name, item) => [
                                                                `${money(val)} (${item?.payload?.pct || 0}%) · Avg: ${money(item?.payload?.avg || 0)}`,
                                                                'Spent'
                                                            ]}
                                                        />
                                                    </PieChart>
                                                </ResponsiveContainer>
                                            </div>
                                            <div className="pie-legend">
                                                {categoryBreakdown.slice(0, 8).map((x, i) => (
                                                    <div
                                                        key={x.category}
                                                        className="pie-legend-row clickable"
                                                        onClick={() => setSelectedCategoryDetail(x.category)}
                                                        title={`Click to view ${x.category} transactions in ${range.label}`}
                                                    >
                                                        <span className="pie-dot" style={{ background: CHART_COLORS[i % CHART_COLORS.length] }} />
                                                        <span className="pie-cat" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                                            <span>{x.category}</span>
                                                            <small style={{ color: 'var(--text-subtle)', fontSize: 11 }}>
                                                                ({x.txns} {x.txns === 1 ? 'txn' : 'txns'} · avg {money(x.avg)})
                                                            </small>
                                                        </span>
                                                        <span className="pie-pct">{x.pct}%</span>
                                                        <b className="pie-amt">{money(x.amount)}</b>
                                                    </div>
                                                ))}
                                            </div>
                                        </>
                                    ) : (
                                        <div className="empty">No expenses recorded in the selected period.</div>
                                    )}
                                </section>

                                {/* Spends by Payment Method Donut Chart */}
                                <section className="panel report-chart-panel">
                                    <div className="card-head">
                                        <div className="label"><i className="ico"><CreditCard size={16} /></i>Spends by Payment Method</div>
                                        <span className="pill">{range.label}</span>
                                    </div>
                                    {paymentBreakdown?.filter(x => x.amount > 0).length ? (
                                        <>
                                            <div style={{ height: 230, marginTop: 8 }}>
                                                <ResponsiveContainer width="100%" height="100%">
                                                    <PieChart>
                                                        <Pie
                                                            data={paymentBreakdown.filter(x => x.amount > 0)}
                                                            dataKey="amount"
                                                            nameKey="payment_method"
                                                            innerRadius={60}
                                                            outerRadius={95}
                                                            paddingAngle={2}
                                                            stroke="var(--card)"
                                                            strokeWidth={2}
                                                            onClick={entry => {
                                                                if (entry?.payment_method) setSelectedPaymentDetail(entry.payment_method);
                                                            }}
                                                            style={{ cursor: 'pointer' }}
                                                        >
                                                            {paymentBreakdown.filter(x => x.amount > 0).map((x, i) => (
                                                                <Cell key={x.payment_method} fill={getPaymentChartColor(x.payment_method, i)} />
                                                            ))}
                                                        </Pie>
                                                        <Tooltip
                                                            formatter={(val, name, item) => [
                                                                `${money(val)} (${item?.payload?.pct || 0}%) · Avg: ${money(item?.payload?.avg || 0)}`,
                                                                'Spent'
                                                            ]}
                                                        />
                                                    </PieChart>
                                                </ResponsiveContainer>
                                            </div>
                                            <div className="pie-legend">
                                                {paymentBreakdown.filter(x => x.amount > 0).map((x, i) => {
                                                    const avgExp = x.avg || (x.exp_txns ? Math.round(x.amount / x.exp_txns) : (x.txns ? Math.round(x.amount / x.txns) : 0));
                                                    return (
                                                        <div
                                                            key={x.payment_method}
                                                            className="pie-legend-row clickable"
                                                            onClick={() => setSelectedPaymentDetail(x.payment_method)}
                                                            title={`Click to view ${x.payment_method} transactions in ${range.label}`}
                                                        >
                                                            <span className="pie-dot" style={{ background: getPaymentChartColor(x.payment_method, i) }} />
                                                            <span className="pie-cat" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                                                <span className="pay-badge-colored" style={getPaymentStyle(x.payment_method)}>
                                                                    {x.payment_method}
                                                                </span>
                                                                <small style={{ color: 'var(--text-subtle)', fontSize: 11 }}>
                                                                    ({x.txns} {x.txns === 1 ? 'txn' : 'txns'} · avg {money(avgExp)})
                                                                </small>
                                                            </span>
                                                            <span className="pie-pct">{x.pct}%</span>
                                                            <b className="pie-amt">{money(x.amount)}</b>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        </>
                                    ) : (
                                        <div className="empty">No payment spends recorded in the selected period.</div>
                                    )}
                                </section>

                                {/* ── ROW 3: Payment Channel Insights ── */}
                                <section className="panel report-chart-panel report-full">
                                    <div className="card-head">
                                        <div className="label"><i className="ico"><Landmark size={16} /></i>Payment Channel Insights</div>
                                        <span className="pill">Channel Metrics</span>
                                    </div>
                                    <div className="payment-insights-grid">
                                        <div className="payment-insight-card">
                                            <small>PRIMARY SPEND CHANNEL</small>
                                            {paymentBreakdown.find(x => x.amount > 0) ? (
                                                <>
                                                    <div className="insight-badge-row">
                                                        <span className="pay-badge-colored" style={getPaymentStyle(paymentBreakdown[0].payment_method)}>
                                                            {paymentBreakdown[0].payment_method}
                                                        </span>
                                                        <span className="insight-pct red-badge">{paymentBreakdown[0].pct}% of spends</span>
                                                    </div>
                                                    <b className="insight-val red-text">{money(paymentBreakdown[0].amount)}</b>
                                                    <span className="insight-sub">{paymentBreakdown[0].exp_txns || paymentBreakdown[0].txns} {(paymentBreakdown[0].exp_txns || paymentBreakdown[0].txns) === 1 ? 'outflow transaction' : 'outflow transactions'}</span>
                                                </>
                                            ) : <span className="muted">No data</span>}
                                        </div>
                                        <div className="payment-insight-card">
                                            <small>TOP INFLOW CHANNEL</small>
                                            {(() => {
                                                const topInc = [...paymentBreakdown].sort((a, b) => b.income - a.income).find(x => x.income > 0);
                                                return topInc ? (
                                                    <>
                                                        <div className="insight-badge-row">
                                                            <span className="pay-badge-colored" style={getPaymentStyle(topInc.payment_method)}>{topInc.payment_method}</span>
                                                            <span className="insight-pct green-badge">Primary deposit</span>
                                                        </div>
                                                        <b className="insight-val green">{money(topInc.income)}</b>
                                                        <span className="insight-sub">{topInc.inc_txns || topInc.txns} {(topInc.inc_txns || topInc.txns) === 1 ? 'income transaction' : 'income transactions'}</span>
                                                    </>
                                                ) : <span className="muted">No income in period</span>;
                                            })()}
                                        </div>
                                        <div className="payment-insight-card">
                                            <small>CHANNEL UTILIZATION</small>
                                            <b className="insight-val">{paymentBreakdown.filter(x => x.txns > 0).length} active methods</b>
                                            <div className="insight-sub" style={{ marginTop: 4 }}>
                                                Total <b>{paymentBreakdown.reduce((s, x) => s + x.txns, 0)}</b> transactions across channels
                                            </div>
                                        </div>
                                        <div className="payment-insight-card">
                                            <small>AVERAGE TICKET SIZE</small>
                                            {(() => {
                                                const totalExp = paymentBreakdown.reduce((s, x) => s + x.amount, 0);
                                                const expTxns = tx.filter(t => t.kind === 'expense').length;
                                                return (
                                                    <>
                                                        <b className="insight-val">{money(expTxns ? Math.round(totalExp / expTxns) : 0)}</b>
                                                        <span className="insight-sub">Average per expense transaction</span>
                                                    </>
                                                );
                                            })()}
                                        </div>
                                        <div className="payment-insight-card channel-net-card">
                                            <small>NET FLOW BY CHANNEL</small>
                                            <div className="channel-net-list">
                                                {[...paymentBreakdown].sort((a, b) => Math.abs(b.net) - Math.abs(a.net)).slice(0, 4).map(x => {
                                                    const positive = x.net >= 0;
                                                    const maxNet = Math.max(...paymentBreakdown.map(p => Math.abs(p.net)), 1);
                                                    return (
                                                        <button
                                                            key={x.payment_method}
                                                            type="button"
                                                            className="channel-net-row"
                                                            onClick={() => setSelectedPaymentDetail(x.payment_method)}
                                                            title={`View ${x.payment_method} transactions`}
                                                        >
                                                            <span className="channel-net-name">{x.payment_method}</span>
                                                            <span className="channel-net-track">
                                                                <i
                                                                    className={positive ? 'is-pos' : 'is-neg'}
                                                                    style={{ width: `${Math.max(6, (Math.abs(x.net) / maxNet) * 100)}%` }}
                                                                />
                                                            </span>
                                                            <b className={positive ? 'is-pos' : 'is-neg'}>
                                                                {positive ? '+' : '−'}{money(Math.abs(x.net))}
                                                            </b>
                                                        </button>
                                                    );
                                                })}
                                                {!paymentBreakdown.length && <span className="muted">No channels in period</span>}
                                            </div>
                                        </div>
                                    </div>
                                </section>

                                {/* ── ROW 4: Detailed Breakdown Table ── */}

                                {/* Full Breakdown Table with Category & Payment Method Tabs */}
                                <section className="panel report-chart-panel report-full">
                                    <div className="card-head" style={{ flexWrap: 'wrap', gap: 12 }}>
                                        <SegmentedTabs
                                            ariaLabel="Breakdown"
                                            value={reportBreakdownTab}
                                            onChange={setReportBreakdownTab}
                                            items={[
                                                { value: 'category', label: 'By Category', count: analytics?.category_breakdown?.length || 0, icon: <Wallet size={14} /> },
                                                { value: 'payment', label: 'By Payment Method', count: paymentBreakdown?.length || 0, icon: <CreditCard size={14} /> },
                                            ]}
                                        />
                                        <small style={{ color: 'var(--muted-foreground)', fontWeight: 500 }}>(Click any row to drill down into exact transactions)</small>
                                    </div>

                                    {reportBreakdownTab === 'category' ? (
                                        categoryBreakdown?.length ? (
                                            <div className="table-wrap">
                                                <table>
                                                    <thead>
                                                        <tr>
                                                            <th>Category</th>
                                                            <th>Total Spends</th>
                                                            <th>Transactions</th>
                                                            <th>Avg / Txn</th>
                                                            <th>% of Total Expense</th>
                                                            <th>Proportion</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                                        {categoryBreakdown.map((x, i) => (
                                                            <tr
                                                                key={x.category}
                                                                className="clickable-category-row"
                                                                onClick={() => setSelectedCategoryDetail(x.category)}
                                                                title={`Click to view exact transactions for ${x.category} (${range.label})`}
                                                            >
                                                                <td>
                                                                    <span className="cat-badge-colored" style={getCategoryStyle(x.category)}>
                                                                        {x.category}
                                                                    </span>
                                                                </td>
                                                                <td><b className="red-text">{money(x.amount)}</b></td>
                                                                <td>
                                                                    <span className="tx-count-pill" style={{ padding: '2px 8px', fontSize: 12 }}>
                                                                        {x.txns} {x.txns === 1 ? 'txn' : 'txns'}
                                                                    </span>
                                                                </td>
                                                                <td>
                                                                    <b style={{ fontSize: 13, color: 'var(--text-main)' }}>
                                                                        {money(x.avg)}
                                                                    </b>
                                                                </td>
                                                                <td>{x.pct}%</td>
                                                                <td style={{ minWidth: 140 }}>
                                                                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                                                        <div style={{ flex: 1, background: 'var(--muted)', borderRadius: 999, height: 8, overflow: 'hidden' }}>
                                                                            <div style={{ width: `${x.pct}%`, height: '100%', background: CHART_COLORS[i % CHART_COLORS.length], borderRadius: 999 }} />
                                                                        </div>
                                                                        <ArrowUpRight size={14} className="row-action-arrow" />
                                                                    </div>
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            </div>
                                        ) : (
                                            <div className="empty">Select a range to see category breakdown.</div>
                                        )
                                    ) : (
                                        paymentBreakdown?.length ? (
                                            <div className="table-wrap">
                                                <table>
                                                    <thead>
                                                        <tr>
                                                            <th>Payment Method</th>
                                                            <th>Outflow (Spends)</th>
                                                            <th>Inflow (Received)</th>
                                                            <th>Net Cashflow</th>
                                                            <th>Transactions</th>
                                                            <th>Avg Outflow</th>
                                                            <th>Avg Inflow</th>
                                                            <th>% of Total Spends</th>
                                                            <th>Proportion</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                                        {paymentBreakdown.map((x, i) => {
                                                            const avgOut = x.avg || (x.exp_txns ? Math.round(x.amount / x.exp_txns) : (x.amount > 0 && x.txns ? Math.round(x.amount / x.txns) : 0));
                                                            const avgIn = x.avg_income || (x.inc_txns ? Math.round(x.income / x.inc_txns) : (x.income > 0 && x.txns ? Math.round(x.income / x.txns) : 0));
                                                            return (
                                                                <tr
                                                                    key={x.payment_method}
                                                                    className="clickable-category-row"
                                                                    onClick={() => setSelectedPaymentDetail(x.payment_method)}
                                                                    title={`Click to view exact transactions for ${x.payment_method} (${range.label})`}
                                                                >
                                                                    <td>
                                                                        <span className="pay-badge-colored" style={getPaymentStyle(x.payment_method)}>
                                                                            {x.payment_method}
                                                                        </span>
                                                                    </td>
                                                                    <td>
                                                                        <b className={x.amount > 0 ? "red-text" : "muted"}>
                                                                            {x.amount > 0 ? money(x.amount) : '₹0'}
                                                                        </b>
                                                                    </td>
                                                                    <td>
                                                                        <b className={x.income > 0 ? "green" : "muted"}>
                                                                            {x.income > 0 ? money(x.income) : '₹0'}
                                                                        </b>
                                                                    </td>
                                                                    <td>
                                                                        <b className={x.net >= 0 ? "green" : "red-text"}>
                                                                            {x.net >= 0 ? '+' : '−'}{money(Math.abs(x.net))}
                                                                        </b>
                                                                    </td>
                                                                    <td>
                                                                        <span className="tx-count-pill" style={{ padding: '2px 8px', fontSize: 12 }}>
                                                                            {x.txns}
                                                                        </span>
                                                                    </td>
                                                                    <td>
                                                                        <b style={{ fontSize: 13, color: avgOut > 0 ? 'var(--chart-1)' : 'var(--text-subtle)' }}>
                                                                            {avgOut > 0 ? money(avgOut) : '—'}
                                                                        </b>
                                                                    </td>
                                                                    <td>
                                                                        <b style={{ fontSize: 13, color: avgIn > 0 ? 'var(--chart-2)' : 'var(--text-subtle)' }}>
                                                                            {avgIn > 0 ? money(avgIn) : '—'}
                                                                        </b>
                                                                    </td>
                                                                    <td>{x.pct}%</td>
                                                                    <td style={{ minWidth: 140 }}>
                                                                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                                                            <div style={{ flex: 1, background: 'var(--muted)', borderRadius: 999, height: 8, overflow: 'hidden' }}>
                                                                                <div style={{ width: `${x.pct}%`, height: '100%', background: getPaymentChartColor(x.payment_method, i), borderRadius: 6 }} />
                                                                            </div>
                                                                            <ArrowUpRight size={14} className="row-action-arrow" />
                                                                        </div>
                                                                    </td>
                                                                </tr>
                                                            );
                                                        })}
                                                    </tbody>
                                                </table>
                                            </div>
                                        ) : (
                                            <div className="empty">No payment methods recorded in the selected period.</div>
                                        )
                                    )}
                                </section>
                            </div>
                        </div>
                    )}

                </div>
                <footer className="page-footer">
                    NIRVAAH <span>·</span> A considered view of your money.
                    <span className="app-version">v{typeof __APP_VERSION__ === 'undefined' ? '1.0.0' : __APP_VERSION__}</span>
                </footer>
            </main>

            {/* ── Modal Dialog with Segmented Type & Custom Dropdowns ────────────── */}
            {modal && page !== 'Transactions' && (
                <Modal
                    page={page}
                    form={form}
                    setForm={setForm}
                    save={save}
                    close={() => setModal(false)}
                    busy={busy}
                    error={error}
                    expenseCats={expenseCats}
                    incomeCats={incomeCats}
                    paymentMethods={paymentMethods}
                    onOpenManage={tab => setManageModal(tab)}
                />
            )}

            {/* ── Manage Categories & Payment Methods Modal ────────────────────── */}
            {manageModal && (
                <ManageTagsModal
                    activeTab={manageModal}
                    onClose={() => setManageModal(null)}
                    expenseCats={expenseCats}
                    incomeCats={incomeCats}
                    paymentMethods={paymentMethods}
                    onAddExpenseCat={handleAddExpenseCat}
                    onRemoveExpenseCat={handleRemoveExpenseCat}
                    onAddIncomeCat={handleAddIncomeCat}
                    onRemoveIncomeCat={handleRemoveIncomeCat}
                    onAddPaymentMethod={handleAddPaymentMethod}
                    onRemovePaymentMethod={handleRemovePaymentMethod}
                    onResetDefaults={handleResetDefaults}
                    getCategoryStyle={getCategoryStyle}
                    getPaymentStyle={getPaymentStyle}
                />
            )}

            {/* ── Category Transactions Drilldown Modal ────────────────────── */}
            {selectedCategoryDetail && (
                <CategoryDrilldownModal
                    type="category"
                    category={selectedCategoryDetail}
                    rangeLabel={range.label}
                    transactions={tx.filter(t => t.category === selectedCategoryDetail)}
                    onClose={() => setSelectedCategoryDetail(null)}
                    onNavigateToTransactions={() => {
                        const cat = selectedCategoryDetail;
                        setSelectedCategoryDetail(null);
                        setFilterKind('All');
                        setFilterCategory(cat);
                        navigateTo('Transactions');
                    }}
                    getCategoryStyle={getCategoryStyle}
                    getPaymentStyle={getPaymentStyle}
                    onEditTx={openEditTx}
                    onDeleteTx={id => del('transactions', id)}
                />
            )}

            {/* ── Payment Method Transactions Drilldown Modal ──────────────── */}
            {selectedPaymentDetail && (
                <CategoryDrilldownModal
                    type="payment"
                    category={selectedPaymentDetail}
                    rangeLabel={range.label}
                    transactions={tx.filter(t => (t.payment_method || '').toLowerCase() === selectedPaymentDetail.toLowerCase())}
                    onClose={() => setSelectedPaymentDetail(null)}
                    onNavigateToTransactions={() => {
                        const pm = selectedPaymentDetail;
                        setSelectedPaymentDetail(null);
                        setFilterKind('All');
                        setFilterCategory('All');
                        setSearch(pm);
                        navigateTo('Transactions');
                    }}
                    getCategoryStyle={getCategoryStyle}
                    getPaymentStyle={getPaymentStyle}
                    onEditTx={openEditTx}
                    onDeleteTx={id => del('transactions', id)}
                />
            )}

            {/* ── Edit Transaction Modal ────────────────────────────────────── */}
            {editingTx && (
                <EditTransactionModal
                    tx={editingTx}
                    setTx={setEditingTx}
                    onSave={handleSaveEditTx}
                    onClose={() => setEditingTx(null)}
                    busy={editBusy}
                    error={editError}
                    expenseCats={expenseCats}
                    incomeCats={incomeCats}
                    paymentMethods={paymentMethods}
                    onOpenManage={setManageModal}
                />
            )}
        </div>
        </>
    );
}

// ── Polished Modal with Segmented Type Buttons & CustomSelect ─────────────────
function Modal({
    page, form, setForm, save, close, busy, error,
    expenseCats, incomeCats, paymentMethods, onOpenManage,
}) {
    const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }));
    const setType = newKind => {
        const defaultCat = newKind === 'income' ? (incomeCats[0] || 'Salary') : (expenseCats[0] || 'Groceries');
        setForm(prev => ({
            ...prev,
            kind: newKind,
            category: defaultCat,
        }));
    };

    const catOptions = form.kind === 'income' ? incomeCats : expenseCats;

    return (
        <div className="overlay" onMouseDown={e => e.target === e.currentTarget && close()}>
            <form className="modal" onSubmit={save}>
                <div className="modal-head">
                    <div>
                        <small>ADD TO NIRVAAH</small>
                        <h2>{page === 'Transactions' ? 'New transaction' : page === 'Savings goals' ? 'New savings goal' : `New ${singularPage(page)}`}</h2>
                    </div>
                    <button type="button" className="icon-btn" onClick={close}><X /></button>
                </div>

                {page === 'Transactions' && (
                    <>
                        <div className="form-group">
                            <span className="form-label">Transaction Type</span>
                            <div className="type-toggle">
                                <button
                                    type="button"
                                    className={`type-btn ${form.kind === 'expense' ? 'active is-expense' : ''}`}
                                    onClick={() => setType('expense')}
                                >
                                    <ArrowUpRight size={16} /> Expense
                                </button>
                                <button
                                    type="button"
                                    className={`type-btn ${form.kind === 'income' ? 'active is-income' : ''}`}
                                    onClick={() => setType('income')}
                                >
                                    <ArrowDownLeft size={16} /> Income
                                </button>
                            </div>
                        </div>

                        <div className="form-group">
                            <span className="form-label">Amount (₹)</span>
                            <input
                                required
                                type="number"
                                step="any"
                                min="0.01"
                                placeholder="0.00"
                                value={form.amount ?? ''}
                                onChange={e => set('amount', e.target.value)}
                            />
                        </div>

                        <div className="form-group">
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span className="form-label">Category</span>
                                <button
                                    type="button"
                                    className="link"
                                    style={{ fontSize: '11px', textDecoration: 'none' }}
                                    onClick={() => onOpenManage(form.kind === 'income' ? 'income' : 'expense')}
                                >
                                    + Add / Remove
                                </button>
                            </div>
                            <CustomSelect
                                value={form.category && catOptions.includes(form.category) ? form.category : (catOptions[0] || '')}
                                onChange={v => set('category', v)}
                                options={catOptions}
                                fullWidth
                            />
                        </div>

                        <div className="form-group">
                            <span className="form-label">Description</span>
                            <input
                                type="text"
                                placeholder="e.g. Grocery store, Netflix, Uber, Salary…"
                                value={form.description ?? ''}
                                onChange={e => set('description', e.target.value)}
                            />
                        </div>

                        <div className="form-group">
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span className="form-label">Payment method</span>
                                <button
                                    type="button"
                                    className="link"
                                    style={{ fontSize: '11px', textDecoration: 'none' }}
                                    onClick={() => onOpenManage('payment')}
                                >
                                    + Add / Remove
                                </button>
                            </div>
                            <CustomSelect
                                value={form.payment_method && paymentMethods.includes(form.payment_method) ? form.payment_method : (paymentMethods[0] || 'SBI')}
                                onChange={v => set('payment_method', v)}
                                options={paymentMethods}
                                fullWidth
                                dropUp={true}
                            />
                        </div>

                        <div className="form-group">
                            <span className="form-label">Date</span>
                            <input
                                required
                                type="date"
                                value={form.txn_date ?? today()}
                                onChange={e => set('txn_date', e.target.value)}
                            />
                        </div>
                    </>
                )}

                {page === 'Budgets' && (
                    <>
                        <div className="form-group">
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span className="form-label">Category</span>
                                <button
                                    type="button"
                                    className="link"
                                    style={{ fontSize: '11px', textDecoration: 'none' }}
                                    onClick={() => onOpenManage('expense')}
                                >
                                    + Add / Remove
                                </button>
                            </div>
                            <CustomSelect
                                value={form.category && expenseCats.includes(form.category) ? form.category : (expenseCats[0] || 'Groceries')}
                                onChange={v => set('category', v)}
                                options={expenseCats}
                                fullWidth
                            />
                        </div>
                        <div className="form-group">
                            <span className="form-label">Monthly limit (₹)</span>
                            <input required type="number" min="1" value={form.monthly_limit ?? ''} onChange={e => set('monthly_limit', e.target.value)} />
                        </div>
                        <div className="form-group">
                            <span className="form-label">Month</span>
                            <CustomSelect
                                value={form.month ?? thisMonthStr()}
                                onChange={v => set('month', v)}
                                options={monthOptions()}
                                fullWidth
                            />
                        </div>
                    </>
                )}

                {page === 'Savings goals' && (
                    <>
                        <div className="form-group">
                            <span className="form-label">Goal name</span>
                            <input required type="text" placeholder="e.g. Emergency Fund" value={form.name ?? ''} onChange={e => set('name', e.target.value)} />
                        </div>
                        <div className="form-group">
                            <span className="form-label">Target amount (₹)</span>
                            <input required type="number" min="1" value={form.target_amount ?? ''} onChange={e => set('target_amount', e.target.value)} />
                        </div>
                        <div className="form-group">
                            <span className="form-label">Already saved (₹)</span>
                            <input type="number" min="0" value={form.saved_amount ?? '0'} onChange={e => set('saved_amount', e.target.value)} />
                        </div>
                        <div className="form-group">
                            <span className="form-label">Target date</span>
                            <input type="date" value={form.target_date ?? ''} onChange={e => set('target_date', e.target.value)} />
                        </div>
                    </>
                )}

                {page === 'Investments' && (
                    <>
                        <div className="form-group">
                            <span className="form-label">Investment name</span>
                            <input required type="text" placeholder="e.g. Nifty 50 Index Fund" value={form.name ?? ''} onChange={e => set('name', e.target.value)} />
                        </div>
                        <div className="form-group">
                            <span className="form-label">Asset type</span>
                            <CustomSelect
                                value={form.asset_type || 'Mutual Fund'}
                                onChange={v => set('asset_type', v)}
                                options={['Mutual Fund', 'Stocks', 'ETF', 'Fixed Deposit', 'PPF', 'NPS', 'Gold', 'Real Estate', 'Other']}
                                fullWidth
                            />
                        </div>
                        <div className="form-group">
                            <span className="form-label">Invested amount (₹)</span>
                            <input required type="number" min="0" value={form.invested_amount ?? ''} onChange={e => set('invested_amount', e.target.value)} />
                        </div>
                        <div className="form-group">
                            <span className="form-label">Current value (₹)</span>
                            <input required type="number" min="0" value={form.current_value ?? ''} onChange={e => set('current_value', e.target.value)} />
                        </div>
                        <div className="form-group">
                            <span className="form-label">Notes</span>
                            <input type="text" value={form.notes ?? ''} onChange={e => set('notes', e.target.value)} />
                        </div>
                    </>
                )}

                {page === 'Liabilities' && (
                    <>
                        <div className="form-group">
                            <span className="form-label">Liability name</span>
                            <input required type="text" placeholder="e.g. HDFC Home Loan" value={form.name ?? ''} onChange={e => set('name', e.target.value)} />
                        </div>
                        <div className="form-group">
                            <span className="form-label">Type</span>
                            <CustomSelect
                                value={form.liability_type || 'Home Loan'}
                                onChange={v => set('liability_type', v)}
                                options={['Home Loan', 'Personal Loan', 'Car Loan', 'Education Loan', 'Credit Card', 'Other']}
                                fullWidth
                            />
                        </div>
                        <div className="form-group">
                            <span className="form-label">Outstanding amount (₹)</span>
                            <input required type="number" min="0" value={form.outstanding_amount ?? ''} onChange={e => set('outstanding_amount', e.target.value)} />
                        </div>
                        <div className="form-group">
                            <span className="form-label">Monthly EMI (₹)</span>
                            <input type="number" min="0" value={form.monthly_emi ?? '0'} onChange={e => set('monthly_emi', e.target.value)} />
                        </div>
                        <div className="form-group">
                            <span className="form-label">Notes</span>
                            <input type="text" value={form.notes ?? ''} onChange={e => set('notes', e.target.value)} />
                        </div>
                    </>
                )}

                {error && <div className="error">{error}</div>}
                <div className="modal-actions">
                    <button type="button" className="soft" onClick={close}>Cancel</button>
                    <button className="blue" disabled={busy}>{busy ? 'Saving…' : 'Save record'} <ArrowUpRight size={14} /></button>
                </div>
            </form>
        </div>
    );
}


// ── Manage Categories & Payment Methods Modal ─────────────────────────────────
function ManageTagsModal({
    activeTab = 'expense',
    onClose,
    expenseCats,
    incomeCats,
    paymentMethods,
    onAddExpenseCat,
    onRemoveExpenseCat,
    onAddIncomeCat,
    onRemoveIncomeCat,
    onAddPaymentMethod,
    onRemovePaymentMethod,
    onResetDefaults,
    getCategoryStyle,
    getPaymentStyle,
}) {
    const [tab, setTab] = useState(activeTab);
    const [inputVal, setInputVal] = useState('');

    const handleAdd = e => {
        e.preventDefault();
        const trimmed = inputVal.trim();
        if (!trimmed) return;
        if (tab === 'expense') onAddExpenseCat(trimmed);
        else if (tab === 'income') onAddIncomeCat(trimmed);
        else onAddPaymentMethod(trimmed);
        setInputVal('');
    };

    return (
        <div className="overlay" onMouseDown={e => e.target === e.currentTarget && onClose()}>
            <div className="modal manage-modal" role="dialog" aria-modal="true">
                <div className="modal-head">
                    <div>
                        <small>PREFERENCES &amp; TAGS</small>
                        <h2>Categories &amp; Payment Methods</h2>
                    </div>
                    <button type="button" className="icon-btn" onClick={onClose}><X size={18} /></button>
                </div>

                <SegmentedTabs
                    ariaLabel="Tag type"
                    value={tab}
                    onChange={next => { setTab(next); setInputVal(''); }}
                    items={[
                        { value: 'expense', label: 'Expense', count: expenseCats.length },
                        { value: 'income', label: 'Income', count: incomeCats.length },
                        { value: 'payment', label: 'Payment Methods', count: paymentMethods.length },
                    ]}
                />

                <form className="manage-add-row" onSubmit={handleAdd}>
                    <input
                        placeholder={
                            tab === 'expense'
                                ? 'Add new expense category (e.g. Pet Care, Rent, Gym)…'
                                : tab === 'income'
                                ? 'Add new income category (e.g. Dividend, Bonus)…'
                                : 'Add new payment method (e.g. Google Pay, Axis Bank)…'
                        }
                        value={inputVal}
                        onChange={e => setInputVal(e.target.value)}
                        autoFocus
                    />
                    <button type="submit" className="blue" style={{ padding: '8px 16px', fontSize: '13px' }}>
                        <Plus size={15} /> Add
                    </button>
                </form>

                <div className="manage-chips-wrap">
                    {tab === 'expense' && (
                        expenseCats.map(cat => (
                            <span key={cat} className="manage-chip" style={getCategoryStyle(cat)}>
                                <span>{cat}</span>
                                <button
                                    type="button"
                                    className="manage-chip-del"
                                    onClick={() => onRemoveExpenseCat(cat)}
                                    title={`Remove "${cat}"`}
                                >
                                    ×
                                </button>
                            </span>
                        ))
                    )}

                    {tab === 'income' && (
                        incomeCats.map(cat => (
                            <span key={cat} className="manage-chip" style={getCategoryStyle(cat)}>
                                <span>{cat}</span>
                                <button
                                    type="button"
                                    className="manage-chip-del"
                                    onClick={() => onRemoveIncomeCat(cat)}
                                    title={`Remove "${cat}"`}
                                >
                                    ×
                                </button>
                            </span>
                        ))
                    )}

                    {tab === 'payment' && (
                        paymentMethods.map(m => (
                            <span key={m} className="manage-chip" style={getPaymentStyle(m)}>
                                <span>{m}</span>
                                <button
                                    type="button"
                                    className="manage-chip-del"
                                    onClick={() => onRemovePaymentMethod(m)}
                                    title={`Remove "${m}"`}
                                >
                                    ×
                                </button>
                            </span>
                        ))
                    )}
                </div>

                <div className="manage-footer">
                    <button
                        type="button"
                        className="link"
                        style={{ fontSize: '12px', display: 'inline-flex', alignItems: 'center', gap: '5px' }}
                        onClick={onResetDefaults}
                    >
                        <RotateCcw size={13} /> Reset to defaults
                    </button>
                    <button type="button" className="blue" onClick={onClose} style={{ padding: '7px 20px', fontSize: '13px' }}>
                        Done
                    </button>
                </div>
            </div>
        </div>
    );
}


// ── Transactions Drilldown Modal (Category & Payment Method) ──────────────────
function CategoryDrilldownModal({
    type = 'category',
    category,
    rangeLabel,
    transactions = [],
    onClose,
    onNavigateToTransactions,
    getCategoryStyle,
    getPaymentStyle,
    onEditTx,
    onDeleteTx,
}) {
    const isPayment = type === 'payment';
    const expTxns = useMemo(() => transactions.filter(t => t.kind === 'expense'), [transactions]);
    const incTxns = useMemo(() => transactions.filter(t => t.kind === 'income'), [transactions]);
    const totalSpent = useMemo(() => expTxns.reduce((sum, t) => sum + Number(t.amount || 0), 0), [expTxns]);
    const totalIncome = useMemo(() => incTxns.reduce((sum, t) => sum + Number(t.amount || 0), 0), [incTxns]);
    const net = totalIncome - totalSpent;
    const expenseCount = expTxns.length;
    const incomeCount = incTxns.length;
    const avgSpent = expenseCount ? Math.round(totalSpent / expenseCount) : 0;
    const avgIncome = incomeCount ? Math.round(totalIncome / incomeCount) : 0;

    return (
        <div className="overlay" onMouseDown={e => e.target === e.currentTarget && onClose()}>
            <div className="modal drilldown-modal" role="dialog" aria-modal="true">
                <div className="modal-head" style={{ alignItems: 'flex-start' }}>
                    <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                            {isPayment ? (
                                <span className="pay-badge-colored" style={getPaymentStyle(category)}>
                                    {category}
                                </span>
                            ) : (
                                <span className="cat-badge-colored" style={getCategoryStyle(category)}>
                                    {category}
                                </span>
                            )}
                            <small style={{ color: 'var(--muted-foreground)', fontWeight: 600 }}>
                                {isPayment ? 'PAYMENT CHANNEL BREAKDOWN' : 'CATEGORY BREAKDOWN'} · {rangeLabel}
                            </small>
                        </div>
                        <h2 style={{ margin: 0, display: 'flex', alignItems: 'baseline', gap: '10px' }}>
                            {isPayment ? (
                                <>
                                    <span className={totalSpent > 0 ? "red-text" : "green"}>
                                        {totalSpent > 0 ? money(totalSpent) : money(totalIncome)}
                                    </span>
                                    <span style={{ fontSize: '13px', fontWeight: 500, color: 'var(--muted-foreground)' }}>
                                        ({transactions.length} record{transactions.length === 1 ? '' : 's'})
                                    </span>
                                </>
                            ) : (
                                <>
                                    <span className="red-text">{money(totalSpent)}</span>
                                    <span style={{ fontSize: '14px', fontWeight: 500, color: 'var(--muted-foreground)' }}>
                                        ({transactions.length} record{transactions.length === 1 ? '' : 's'})
                                    </span>
                                </>
                            )}
                        </h2>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <button
                            type="button"
                            className="blue"
                            onClick={onNavigateToTransactions}
                            style={{ padding: '7px 14px', fontSize: '12.5px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
                            title={isPayment ? "Search this payment channel in Transactions" : "Filter by this category in Transactions"}
                        >
                            <span>Open in Transactions</span>
                            <ArrowUpRight size={14} />
                        </button>
                        <button type="button" className="icon-btn" onClick={onClose} title="Close (Esc)"><X size={18} /></button>
                    </div>
                </div>

                <div className="drilldown-stats-row">
                    {isPayment ? (
                        <>
                            <div className="drilldown-stat">
                                <small>Total Outflow</small>
                                <b className="red-text">{money(totalSpent)}</b>
                                <span className="stat-sub">{expenseCount} expense txns</span>
                            </div>
                            <div className="drilldown-stat">
                                <small>Avg Outflow / Txn</small>
                                <b className="red-text">{avgSpent > 0 ? money(avgSpent) : '—'}</b>
                                <span className="stat-sub">per expense transaction</span>
                            </div>
                            <div className="drilldown-stat">
                                <small>Total Inflow</small>
                                <b className="green">{money(totalIncome)}</b>
                                <span className="stat-sub">{incomeCount} income txns</span>
                            </div>
                            <div className="drilldown-stat">
                                <small>Avg Inflow / Txn</small>
                                <b className="green">{avgIncome > 0 ? money(avgIncome) : '—'}</b>
                                <span className="stat-sub">per income transaction</span>
                            </div>
                            <div className="drilldown-stat">
                                <small>Net Cashflow</small>
                                <b className={net >= 0 ? "green" : "red-text"}>
                                    {net >= 0 ? '+' : '−'}{money(Math.abs(net))}
                                </b>
                                <span className="stat-sub">inflow minus outflow</span>
                            </div>
                        </>
                    ) : (
                        <>
                            <div className="drilldown-stat">
                                <small>Total Spend</small>
                                <b className="red-text">{money(totalSpent)}</b>
                                <span className="stat-sub">{expenseCount} expense txns</span>
                            </div>
                            <div className="drilldown-stat">
                                <small>Avg Spend / Txn</small>
                                <b className="red-text">{avgSpent > 0 ? money(avgSpent) : '—'}</b>
                                <span className="stat-sub">per transaction</span>
                            </div>
                            {incomeCount > 0 && (
                                <div className="drilldown-stat">
                                    <small>Total Income</small>
                                    <b className="green">{money(totalIncome)}</b>
                                    <span className="stat-sub">{incomeCount} income txns</span>
                                </div>
                            )}
                            {incomeCount > 0 && (
                                <div className="drilldown-stat">
                                    <small>Avg Income / Txn</small>
                                    <b className="green">{avgIncome > 0 ? money(avgIncome) : '—'}</b>
                                    <span className="stat-sub">per income transaction</span>
                                </div>
                            )}
                            <div className="drilldown-stat">
                                <small>All Transactions</small>
                                <b>{transactions.length}</b>
                                <span className="stat-sub">in selected period</span>
                            </div>
                        </>
                    )}
                </div>

                <div className="drilldown-table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>Description</th>
                                <th>Date</th>
                                <th>{isPayment ? 'Category' : 'Payment Method'}</th>
                                <th>Amount</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            {transactions.length ? transactions.map(t => (
                                <tr key={t.id}>
                                    <td><b>{t.description || t.category}</b></td>
                                    <td>
                                        {new Date(t.txn_date + 'T00:00:00').toLocaleDateString('en-IN', {
                                            day: '2-digit',
                                            month: 'short',
                                            year: 'numeric',
                                        })}
                                    </td>
                                    <td>
                                        {isPayment ? (
                                            <span className="cat-badge-colored" style={getCategoryStyle(t.category)}>
                                                {t.category}
                                            </span>
                                        ) : (
                                            <span className="pay-badge-colored" style={getPaymentStyle(t.payment_method)}>
                                                {t.payment_method}
                                            </span>
                                        )}
                                    </td>
                                    <td>
                                        <b className={t.kind === 'income' ? 'green' : 'red-text'}>
                                            {t.kind === 'income' ? '+' : '−'}{money(t.amount)}
                                        </b>
                                    </td>
                                    <td>
                                        <div className="row-actions">
                                            {onEditTx && (
                                                <button
                                                    type="button"
                                                    className="icon-btn edit-btn"
                                                    onClick={() => onEditTx(t)}
                                                    title="Edit record"
                                                >
                                                    <Pencil size={13} />
                                                </button>
                                            )}
                                            <button
                                                type="button"
                                                className="icon-btn delete-btn"
                                                onClick={() => onDeleteTx(t.id)}
                                                title="Delete record"
                                            >
                                                <Trash2 size={13} />
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            )) : (
                                <tr>
                                    <td colSpan={5}>
                                        <div className="empty">No transactions found for {category} in {rangeLabel}.</div>
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>

                <div className="manage-footer" style={{ marginTop: '16px', paddingTop: '14px' }}>
                    <span style={{ fontSize: '12px', color: 'var(--muted-foreground)' }}>
                        Showing {transactions.length} transactions for {category} ({rangeLabel})
                    </span>
                    <button type="button" className="soft" onClick={onClose} style={{ padding: '7px 20px', fontSize: '13px' }}>
                        Close
                    </button>
                </div>
            </div>
        </div>
    );
}

// ── Dedicated Edit Transaction Modal ──────────────────────────────────────────
function EditTransactionModal({
    tx,
    setTx,
    onSave,
    onClose,
    busy,
    error,
    expenseCats,
    incomeCats,
    paymentMethods,
    onOpenManage,
}) {
    const amountRef = useRef(null);

    useEffect(() => {
        setTimeout(() => amountRef.current?.focus(), 80);
        const onEsc = e => { if (e.key === 'Escape') onClose(); };
        window.addEventListener('keydown', onEsc);
        return () => window.removeEventListener('keydown', onEsc);
    }, [onClose]);

    const catOptions = tx.kind === 'income' ? incomeCats : expenseCats;
    const setField = (k, v) => setTx(prev => ({ ...prev, [k]: v }));

    return (
        <div className="overlay" onMouseDown={e => e.target === e.currentTarget && onClose()}>
            <form className="modal edit-modal" onSubmit={onSave} style={{ maxWidth: '480px' }}>
                <div className="modal-head">
                    <div>
                        <small style={{ letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                            TRANSACTION MANAGEMENT
                        </small>
                        <h2 style={{ fontSize: '20px', margin: '4px 0 0 0' }}>Edit Transaction</h2>
                    </div>
                    <button type="button" className="icon-btn" onClick={onClose}><X size={18} /></button>
                </div>

                <div className="form-group">
                    <span className="form-label">Transaction Type</span>
                    <div className="type-toggle">
                        <button
                            type="button"
                            className={`type-btn ${tx.kind === 'expense' ? 'active is-expense' : ''}`}
                            onClick={() => {
                                setTx(prev => ({
                                    ...prev,
                                    kind: 'expense',
                                    category: expenseCats.includes(prev.category) ? prev.category : (expenseCats[0] || 'Groceries')
                                }));
                            }}
                        >
                            <ArrowUpRight size={16} /> Expense
                        </button>
                        <button
                            type="button"
                            className={`type-btn ${tx.kind === 'income' ? 'active is-income' : ''}`}
                            onClick={() => {
                                setTx(prev => ({
                                    ...prev,
                                    kind: 'income',
                                    category: incomeCats.includes(prev.category) ? prev.category : (incomeCats[0] || 'Salary')
                                }));
                            }}
                        >
                            <ArrowDownLeft size={16} /> Income
                        </button>
                    </div>
                </div>

                <div className="form-group">
                    <span className="form-label">Amount (₹)*</span>
                    <input
                        ref={amountRef}
                        required
                        type="number"
                        step="any"
                        min="0.01"
                        placeholder="0.00"
                        value={tx.amount ?? ''}
                        onChange={e => setField('amount', e.target.value)}
                    />
                </div>

                <div className="form-group">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span className="form-label">Category*</span>
                        <button
                            type="button"
                            className="link"
                            style={{ fontSize: '11px', textDecoration: 'none' }}
                            onClick={() => onOpenManage(tx.kind === 'income' ? 'income' : 'expense')}
                        >
                            + Manage
                        </button>
                    </div>
                    <CustomSelect
                        value={tx.category && catOptions.includes(tx.category) ? tx.category : (catOptions[0] || '')}
                        onChange={v => setField('category', v)}
                        options={catOptions}
                        fullWidth
                    />
                </div>

                <div className="form-group">
                    <span className="form-label">Description</span>
                    <input
                        type="text"
                        placeholder="e.g. Grocery store, Netflix, Uber, Salary…"
                        value={tx.description ?? ''}
                        onChange={e => setField('description', e.target.value)}
                    />
                </div>

                <div className="form-group">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span className="form-label">Payment method*</span>
                        <button
                            type="button"
                            className="link"
                            style={{ fontSize: '11px', textDecoration: 'none' }}
                            onClick={() => onOpenManage('payment')}
                        >
                            + Manage
                        </button>
                    </div>
                    <CustomSelect
                        value={tx.payment_method && paymentMethods.includes(tx.payment_method) ? tx.payment_method : (paymentMethods[0] || 'SBI')}
                        onChange={v => setField('payment_method', v)}
                        options={paymentMethods}
                        fullWidth
                        dropUp={true}
                    />
                </div>

                <div className="form-group">
                    <span className="form-label">Date*</span>
                    <input
                        required
                        type="date"
                        value={tx.txn_date ?? today()}
                        onChange={e => setField('txn_date', e.target.value)}
                    />
                </div>

                {error && <div className="inline-tx-error" style={{ marginBottom: 16 }}>{error}</div>}

                <div className="modal-foot">
                    <button type="button" className="ghost" onClick={onClose} disabled={busy}>Cancel</button>
                    <button type="submit" className="blue" disabled={busy || !tx.amount}>
                        {busy ? 'Saving changes…' : 'Save Changes'}
                    </button>
                </div>
            </form>
        </div>
    );
}
