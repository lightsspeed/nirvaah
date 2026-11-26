import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    Plus, Trash2, Pencil, Check, TrendingUp, TrendingDown, Activity, Target,
    ArrowUpRight, ArrowDownLeft, Wallet,
} from 'lucide-react';
import {
    useCollection, logActivity, uid, todayISO, formatDay, TRADES_KEY,
} from './store';
import { PageHero, StatTile, Segmented, EmptyState, Modal } from './ui';
import CustomSelect from '../CustomSelect';
import { useConfirm } from '../ConfirmDialog';

const INR = new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
});
const money = value => INR.format(Number(value) || 0);
const percent = value => `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(2)}%`;

const emptyQuick = () => ({
    trade_date: todayISO(),
    symbol: '',
    side: 'buy',
    quantity: '',
    entry_price: '',
    exit_price: '',
    fees: '',
    setup: '',
    notes: '',
});

function pnlOf(trade) {
    if (trade.exit_price === null || trade.exit_price === '' || trade.exit_price === undefined) return null;
    const quantity = Number(trade.quantity) || 0;
    const entry = Number(trade.entry_price) || 0;
    const exit = Number(trade.exit_price) || 0;
    const fees = Number(trade.fees) || 0;
    return (trade.side === 'sell' ? entry - exit : exit - entry) * quantity - fees;
}

const FILTERS = [
    { id: 'all', label: 'All' },
    { id: 'open', label: 'Open' },
    { id: 'closed', label: 'Closed' },
];

function TradeEditor({ trade, onClose, onSave, onDelete }) {
    const [draft, setDraft] = useState(trade);
    const [error, setError] = useState('');
    const isNew = !trade.symbol;
    const draftPnl = pnlOf(draft);

    const submit = event => {
        event.preventDefault();
        const symbol = draft.symbol.trim().toUpperCase();
        if (!symbol) {
            setError('Add the instrument or symbol.');
            return;
        }
        if (!Number(draft.quantity)) {
            setError('Quantity must be more than zero.');
            return;
        }
        if (draft.entry_price === '' || Number(draft.entry_price) < 0) {
            setError('Add the entry price.');
            return;
        }
        if (draft.exit_price !== '' && draft.exit_price != null && Number(draft.exit_price) < 0) {
            setError('Exit price cannot be negative.');
            return;
        }
        onSave({
            ...draft,
            symbol,
            quantity: Number(draft.quantity),
            entry_price: Number(draft.entry_price),
            exit_price: draft.exit_price === '' || draft.exit_price == null ? null : Number(draft.exit_price),
            fees: Number(draft.fees) || 0,
            updatedAt: Date.now(),
        });
    };

    return (
        <Modal
            title={isNew ? 'New trade' : 'Edit trade'}
            subtitle={isNew ? 'JOURNAL ENTRY' : formatDay(trade.trade_date).toUpperCase()}
            onClose={onClose}
            footer={(
                <>
                    <div className="life-modal-left">
                        {!isNew && (
                            <button type="button" className="life-btn is-ghost is-danger" onClick={() => onDelete(trade)}>
                                <Trash2 size={14} /> Delete
                            </button>
                        )}
                    </div>
                    <button type="button" className="life-btn" onClick={onClose}>Cancel</button>
                    <button type="button" className="life-btn is-primary" onClick={submit}>
                        <Check size={14} /> {isNew ? 'Save trade' : 'Save changes'}
                    </button>
                </>
            )}
        >
            <form className="trade-form" onSubmit={submit}>
                <div className="trade-form-grid">
                    <label className="life-field">
                        <span className="life-field-label">Date</span>
                        <input
                            className="life-input"
                            type="date"
                            value={draft.trade_date}
                            onChange={e => setDraft({ ...draft, trade_date: e.target.value })}
                        />
                    </label>
                    <label className="life-field">
                        <span className="life-field-label">Symbol / instrument</span>
                        <input
                            className="life-input"
                            placeholder="e.g. NIFTY, RELIANCE, BTC"
                            value={draft.symbol}
                            onChange={e => setDraft({ ...draft, symbol: e.target.value.toUpperCase() })}
                            autoFocus
                        />
                    </label>
                </div>

                <div className="trade-form-grid">
                    <div className="life-field">
                        <span className="life-field-label">Side</span>
                        <CustomSelect
                            value={draft.side}
                            onChange={value => setDraft({ ...draft, side: value })}
                            options={[
                                { value: 'buy', label: 'Buy / Long' },
                                { value: 'sell', label: 'Sell / Short' },
                            ]}
                            fullWidth
                        />
                    </div>
                    <label className="life-field">
                        <span className="life-field-label">Quantity</span>
                        <input
                            className="life-input"
                            type="number"
                            min="0"
                            step="any"
                            inputMode="decimal"
                            placeholder="0"
                            value={draft.quantity}
                            onChange={e => setDraft({ ...draft, quantity: e.target.value })}
                        />
                    </label>
                </div>

                <div className="trade-form-grid">
                    <label className="life-field">
                        <span className="life-field-label">Entry price</span>
                        <input
                            className="life-input"
                            type="number"
                            min="0"
                            step="any"
                            inputMode="decimal"
                            placeholder="0.00"
                            value={draft.entry_price}
                            onChange={e => setDraft({ ...draft, entry_price: e.target.value })}
                        />
                    </label>
                    <label className="life-field">
                        <span className="life-field-label">Exit price <em>blank while open</em></span>
                        <input
                            className="life-input"
                            type="number"
                            min="0"
                            step="any"
                            inputMode="decimal"
                            placeholder="Open position"
                            value={draft.exit_price ?? ''}
                            onChange={e => setDraft({ ...draft, exit_price: e.target.value })}
                        />
                    </label>
                </div>

                <div className="trade-form-grid">
                    <label className="life-field">
                        <span className="life-field-label">Fees</span>
                        <input
                            className="life-input"
                            type="number"
                            min="0"
                            step="any"
                            inputMode="decimal"
                            placeholder="0"
                            value={draft.fees}
                            onChange={e => setDraft({ ...draft, fees: e.target.value })}
                        />
                    </label>
                    <label className="life-field">
                        <span className="life-field-label">Setup / strategy</span>
                        <input
                            className="life-input"
                            placeholder="Breakout, pullback, news…"
                            value={draft.setup}
                            onChange={e => setDraft({ ...draft, setup: e.target.value })}
                        />
                    </label>
                </div>

                <label className="life-field">
                    <span className="life-field-label">Notes</span>
                    <textarea
                        className="life-textarea"
                        rows={3}
                        placeholder="What did you see, what did you learn, what would you repeat?"
                        value={draft.notes}
                        onChange={e => setDraft({ ...draft, notes: e.target.value })}
                    />
                </label>

                {draftPnl !== null && (
                    <div className={`trade-form-pnl ${draftPnl > 0 ? 'is-win' : draftPnl < 0 ? 'is-loss' : ''}`}>
                        <span>Estimated P&amp;L</span>
                        <b>{draftPnl >= 0 ? '+' : '−'}{money(Math.abs(draftPnl))}</b>
                    </div>
                )}
                {error && <div className="trade-form-error" role="alert">{error}</div>}
            </form>
        </Modal>
    );
}

function CloseTradeDialog({ trade, onClose, onSave }) {
    const [exit, setExit] = useState(trade.exit_price == null ? '' : String(trade.exit_price));
    const [fees, setFees] = useState(String(trade.fees ?? 0));
    const [error, setError] = useState('');
    const preview = pnlOf({
        ...trade,
        exit_price: exit === '' ? null : Number(exit),
        fees: Number(fees) || 0,
    });

    const submit = () => {
        if (exit === '' || Number(exit) < 0 || !Number.isFinite(Number(exit))) {
            setError('Add the exit price.');
            return;
        }
        onSave({
            ...trade,
            exit_price: Number(exit),
            fees: Number(fees) || 0,
            updatedAt: Date.now(),
        });
    };

    return (
        <Modal
            title={`Close ${trade.symbol}`}
            subtitle="EXIT & FEES"
            onClose={onClose}
            footer={(
                <>
                    <button type="button" className="life-btn" onClick={onClose}>Cancel</button>
                    <button type="button" className="life-btn is-primary" onClick={submit}>
                        <Check size={14} /> Close trade
                    </button>
                </>
            )}
        >
            <div className="close-summary">
                <span className={`trade-side is-${trade.side}`}>
                    {trade.side === 'sell' ? <ArrowDownLeft size={11} /> : <ArrowUpRight size={11} />}
                    {trade.side === 'sell' ? 'SELL' : 'BUY'}
                </span>
                <b>{trade.quantity} × {money(trade.entry_price)}</b>
                <small>{formatDay(trade.trade_date)}</small>
            </div>

            <div className="trade-form-grid">
                <label className="life-field">
                    <span className="life-field-label">Exit price</span>
                    <input
                        className="life-input"
                        type="number"
                        min="0"
                        step="any"
                        inputMode="decimal"
                        placeholder="0.00"
                        value={exit}
                        onChange={e => setExit(e.target.value)}
                        autoFocus
                    />
                </label>
                <label className="life-field">
                    <span className="life-field-label">Fees</span>
                    <input
                        className="life-input"
                        type="number"
                        min="0"
                        step="any"
                        inputMode="decimal"
                        placeholder="0"
                        value={fees}
                        onChange={e => setFees(e.target.value)}
                    />
                </label>
            </div>

            {preview !== null && (
                <div className={`trade-form-pnl ${preview > 0 ? 'is-win' : preview < 0 ? 'is-loss' : ''}`}>
                    <span>P&amp;L after fees</span>
                    <b>{preview >= 0 ? '+' : '−'}{money(Math.abs(preview))}</b>
                </div>
            )}
            {error && <div className="trade-form-error" role="alert">{error}</div>}
        </Modal>
    );
}

function BudgetEditor({ budget, error, onClose, onSave }) {
    const [draft, setDraft] = useState(budget ? String(budget) : '');
    const [localError, setLocalError] = useState('');

    const submit = () => {
        const value = Number(draft);
        if (draft === '' || !Number.isFinite(value) || value < 0) {
            setLocalError('Enter a budget of zero or more.');
            return;
        }
        onSave(value);
    };

    return (
        <Modal
            title="Trading budget"
            subtitle="JOURNAL SETTING"
            onClose={onClose}
            footer={(
                <>
                    <button type="button" className="life-btn" onClick={onClose}>Cancel</button>
                    <button type="button" className="life-btn is-primary" onClick={submit}>
                        <Check size={14} /> Save budget
                    </button>
                </>
            )}
        >
            <label className="life-field">
                <span className="life-field-label">Budget <em>capital you are running this journal against</em></span>
                <input
                    className="life-input"
                    type="number"
                    min="0"
                    step="any"
                    inputMode="decimal"
                    placeholder="e.g. 100000"
                    value={draft}
                    onChange={e => setDraft(e.target.value)}
                    autoFocus
                />
            </label>
            <p className="trade-budget-note">
                Used only to calculate return on budget. It never changes balances, budgets or reports.
            </p>
            {(localError || error) && <div className="trade-form-error" role="alert">{localError || error}</div>}
        </Modal>
    );
}

export default function TradingJournalPage({ api }) {
    const { ask, dialog } = useConfirm();
    const [trades, setTrades] = useCollection(TRADES_KEY);
    const [filter, setFilter] = useState('all');
    const [editing, setEditing] = useState(null);
    const [closing, setClosing] = useState(null);
    const [budget, setBudget] = useState(0);
    const [editingBudget, setEditingBudget] = useState(false);
    const [budgetError, setBudgetError] = useState('');
    const [quick, setQuick] = useState(emptyQuick);
    const [showMore, setShowMore] = useState(false);
    const symbolRef = useRef(null);

    useEffect(() => {
        if (!api) return undefined;
        let alive = true;
        api.get('/trading/settings')
            .then(res => { if (alive) setBudget(Number(res.data?.budget) || 0); })
            .catch(() => { /* the page still works without a budget */ });
        return () => { alive = false; };
    }, [api]);

    const stats = useMemo(() => {
        const closed = trades
            .map(trade => ({ trade, pnl: pnlOf(trade) }))
            .filter(row => row.pnl !== null);
        const wins = closed.filter(row => row.pnl > 0).length;
        const net = closed.reduce((sum, row) => sum + row.pnl, 0);
        return {
            closed: closed.length,
            open: trades.length - closed.length,
            wins,
            winRate: closed.length ? Math.round((wins / closed.length) * 100) : 0,
            net,
        };
    }, [trades]);

    const returnPct = budget > 0 ? (stats.net / budget) * 100 : null;
    const quickPnl = pnlOf(quick);
    const quickReady = Boolean(quick.symbol.trim()) && Number(quick.quantity) > 0 && quick.entry_price !== '';

    const visible = useMemo(() => {
        const list = trades.filter(trade => {
            if (filter === 'open') return pnlOf(trade) === null;
            if (filter === 'closed') return pnlOf(trade) !== null;
            return true;
        });
        return [...list].sort((a, b) => {
            const byDate = String(b.trade_date).localeCompare(String(a.trade_date));
            return byDate || (b.createdAt || 0) - (a.createdAt || 0);
        });
    }, [trades, filter]);

    const addQuickTrade = event => {
        event.preventDefault();
        if (!quickReady) return;
        const symbol = quick.symbol.trim().toUpperCase();
        const trade = {
            id: uid(),
            trade_date: quick.trade_date || todayISO(),
            symbol,
            side: quick.side,
            quantity: Number(quick.quantity),
            entry_price: Number(quick.entry_price),
            exit_price: quick.exit_price === '' ? null : Number(quick.exit_price),
            fees: Number(quick.fees) || 0,
            setup: quick.setup.trim(),
            notes: quick.notes.trim(),
            createdAt: Date.now(),
            updatedAt: Date.now(),
        };
        setTrades(prev => [trade, ...prev]);
        logActivity(`Trade added: ${symbol}`, 'trade', quick.side);
        setQuick(prev => ({
            ...prev,
            symbol: '', quantity: '', entry_price: '', exit_price: '', fees: '', setup: '', notes: '',
        }));
        symbolRef.current?.focus();
    };

    const saveTrade = draft => {
        const exists = trades.some(trade => trade.id === draft.id);
        setTrades(prev => exists
            ? prev.map(trade => (trade.id === draft.id ? draft : trade))
            : [draft, ...prev]);
        logActivity(
            exists ? `Trade updated: ${draft.symbol}` : `Trade logged: ${draft.symbol}`,
            'trade',
            draft.side,
        );
        setEditing(null);
    };

    const closeTrade = draft => {
        setTrades(prev => prev.map(trade => (trade.id === draft.id ? draft : trade)));
        logActivity(`Trade closed: ${draft.symbol}`, 'trade', draft.side);
        setClosing(null);
    };

    const deleteTrade = async trade => {
        const ok = await ask({
            title: `Delete the ${trade.symbol} trade?`,
            message: 'The journal entry is removed for good. Your balances and reports were never affected.',
            confirmLabel: 'Delete trade',
        });
        if (!ok) return;
        setTrades(prev => prev.filter(item => item.id !== trade.id));
        logActivity(`Trade deleted: ${trade.symbol}`, 'trade');
        setEditing(null);
        setClosing(null);
    };

    const saveBudget = async value => {
        try {
            if (!api) throw new Error('Not connected');
            const res = await api.post('/trading/settings', { budget: value });
            setBudget(Number(res.data?.budget) || 0);
            setBudgetError('');
            setEditingBudget(false);
            logActivity(`Trading budget set to ${money(value)}`, 'trade');
        } catch (err) {
            setBudgetError(err.response?.data?.detail || 'Could not save the budget.');
        }
    };

    return (
        <div className="life-page trading-page">
            {dialog}
            <PageHero>
                <button
                    type="button"
                    className="life-btn is-primary"
                    onClick={() => symbolRef.current?.focus()}
                    aria-label="New trade"
                >
                    <Plus size={15} /><span className="life-btn-label">New trade</span>
                </button>
            </PageHero>

            <div className="trade-budget-strip">
                <div className="trade-budget-cell">
                    <small>TRADING BUDGET</small>
                    <b>{budget > 0 ? money(budget) : 'Not set'}</b>
                </div>
                <div className="trade-budget-cell">
                    <small>RETURN ON BUDGET</small>
                    <b className={returnPct == null ? 'is-muted' : returnPct >= 0 ? 'green' : 'red-text'}>
                        {returnPct == null ? '—' : percent(returnPct)}
                    </b>
                </div>
                <button type="button" className="life-btn is-ghost" onClick={() => { setBudgetError(''); setEditingBudget(true); }}>
                    <Wallet size={13} /> Set budget
                </button>
            </div>

            <div className="panel life-panel trade-composer-panel">
                <form className="trade-quick-add" onSubmit={addQuickTrade}>
                    <div className="trade-quick-row">
                        <input
                            ref={symbolRef}
                            className="life-input"
                            placeholder="Symbol"
                            aria-label="Symbol"
                            value={quick.symbol}
                            onChange={e => setQuick({ ...quick, symbol: e.target.value.toUpperCase() })}
                        />
                        <button
                            type="button"
                            className={`trade-side-btn is-${quick.side}`}
                            onClick={() => setQuick({ ...quick, side: quick.side === 'buy' ? 'sell' : 'buy' })}
                            title={`Switch to ${quick.side === 'buy' ? 'sell' : 'buy'}`}
                        >
                            {quick.side === 'sell' ? <ArrowDownLeft size={13} /> : <ArrowUpRight size={13} />}
                            {quick.side === 'sell' ? 'SELL' : 'BUY'}
                        </button>
                        <input
                            className="life-input"
                            type="number"
                            min="0"
                            step="any"
                            inputMode="decimal"
                            placeholder="Qty"
                            aria-label="Quantity"
                            value={quick.quantity}
                            onChange={e => setQuick({ ...quick, quantity: e.target.value })}
                        />
                        <input
                            className="life-input"
                            type="number"
                            min="0"
                            step="any"
                            inputMode="decimal"
                            placeholder="Entry"
                            aria-label="Entry price"
                            value={quick.entry_price}
                            onChange={e => setQuick({ ...quick, entry_price: e.target.value })}
                        />
                        <input
                            className="life-input"
                            type="number"
                            min="0"
                            step="any"
                            inputMode="decimal"
                            placeholder="Exit (optional)"
                            aria-label="Exit price"
                            value={quick.exit_price}
                            onChange={e => setQuick({ ...quick, exit_price: e.target.value })}
                        />
                        <input
                            className="life-input"
                            type="number"
                            min="0"
                            step="any"
                            inputMode="decimal"
                            placeholder="Fees"
                            aria-label="Fees"
                            value={quick.fees}
                            onChange={e => setQuick({ ...quick, fees: e.target.value })}
                        />
                        {quickPnl !== null && (
                            <span className={`trade-quick-pnl ${quickPnl > 0 ? 'is-win' : quickPnl < 0 ? 'is-loss' : ''}`}>
                                {quickPnl >= 0 ? '+' : '−'}{money(Math.abs(quickPnl))}
                            </span>
                        )}
                        <button type="submit" className="life-btn is-primary" disabled={!quickReady}>
                            <Plus size={14} /> Add
                        </button>
                        <button type="button" className="life-btn is-ghost" onClick={() => setShowMore(v => !v)}>
                            {showMore ? 'Less' : 'Details'}
                        </button>
                    </div>

                    {showMore && (
                        <div className="trade-quick-more">
                            <label className="life-field">
                                <span className="life-field-label">Date</span>
                                <input
                                    className="life-input"
                                    type="date"
                                    value={quick.trade_date}
                                    onChange={e => setQuick({ ...quick, trade_date: e.target.value })}
                                />
                            </label>
                            <label className="life-field">
                                <span className="life-field-label">Setup</span>
                                <input
                                    className="life-input"
                                    placeholder="Breakout, pullback…"
                                    value={quick.setup}
                                    onChange={e => setQuick({ ...quick, setup: e.target.value })}
                                />
                            </label>
                            <label className="life-field is-grow">
                                <span className="life-field-label">Notes</span>
                                <input
                                    className="life-input"
                                    placeholder="Optional context"
                                    value={quick.notes}
                                    onChange={e => setQuick({ ...quick, notes: e.target.value })}
                                />
                            </label>
                        </div>
                    )}
                </form>
            </div>

            <div className="life-stats">
                <StatTile label="Closed trades" value={stats.closed} hint="With an exit price" icon={Check} tint="#6a9bd0" />
                <StatTile label="Win rate" value={`${stats.winRate}%`} hint={`${stats.wins} winner${stats.wins === 1 ? '' : 's'}`} icon={Target} tint="#7fa650" />
                <StatTile
                    label="Net P&L"
                    value={`${stats.net >= 0 ? '+' : '−'}${money(Math.abs(stats.net))}`}
                    hint="After fees, closed trades only"
                    icon={stats.net >= 0 ? TrendingUp : TrendingDown}
                    tint={stats.net >= 0 ? '#7fa650' : '#d97757'}
                />
                <StatTile label="Open" value={stats.open} hint="Waiting for an exit" icon={Activity} tint="#c9a227" />
            </div>

            <div className="life-toolbar">
                <Segmented options={FILTERS} value={filter} onChange={setFilter} />
                <span className="trade-count">{visible.length} {visible.length === 1 ? 'entry' : 'entries'}</span>
            </div>

            <div className="panel life-panel">
                <div className="life-scroll">
                    {visible.length === 0 ? (
                        <EmptyState
                            icon={Activity}
                            title={filter === 'all' ? 'No trades logged yet' : `No ${filter} trades`}
                            hint={filter === 'all'
                                ? 'Log a trade in the bar above — symbol, side, quantity, entry. Exit can come later.'
                                : 'Try another filter, or log a new trade.'}
                        />
                    ) : (
                        <div className="trades-grid">
                            {visible.map(trade => {
                                const pnl = pnlOf(trade);
                                const win = pnl !== null && pnl > 0;
                                const loss = pnl !== null && pnl < 0;
                                return (
                                    <article
                                        className={`trade-card${win ? ' is-win' : loss ? ' is-loss' : ''}`}
                                        key={trade.id}
                                        onClick={() => setEditing(trade)}
                                        onKeyDown={e => { if (e.key === 'Enter') setEditing(trade); }}
                                        role="button"
                                        tabIndex={0}
                                        aria-label={`Edit ${trade.symbol} trade`}
                                    >
                                        <header>
                                            <div className="trade-symbol">
                                                <b>{trade.symbol}</b>
                                                <span className={`trade-side is-${trade.side}`}>
                                                    {trade.side === 'sell' ? <ArrowDownLeft size={11} /> : <ArrowUpRight size={11} />}
                                                    {trade.side === 'sell' ? 'SELL' : 'BUY'}
                                                </span>
                                            </div>
                                            <div className={`trade-pnl ${win ? 'is-win' : loss ? 'is-loss' : 'is-open'}`}>
                                                {pnl === null ? 'OPEN' : `${pnl >= 0 ? '+' : '−'}${money(Math.abs(pnl))}`}
                                            </div>
                                        </header>
                                        <div className="trade-detail">
                                            <span>{formatDay(trade.trade_date)}</span>
                                            <span>{trade.quantity} × {money(trade.entry_price)}</span>
                                            <span>{trade.exit_price == null ? 'still open' : `→ ${money(trade.exit_price)}`}</span>
                                            {Number(trade.fees) > 0 && <span>fees {money(trade.fees)}</span>}
                                        </div>
                                        {trade.setup && <span className="trade-setup">{trade.setup}</span>}
                                        {trade.notes && <p className="trade-notes">{trade.notes}</p>}
                                        <div className="trade-actions" onClick={e => e.stopPropagation()}>
                                            {pnl === null && (
                                                <button
                                                    type="button"
                                                    className="life-btn is-primary trade-close-btn"
                                                    onClick={() => setClosing(trade)}
                                                >
                                                    <Check size={12} /> Close
                                                </button>
                                            )}
                                            <button type="button" className="life-icon-btn" title="Edit trade" onClick={() => setEditing(trade)}>
                                                <Pencil size={13} />
                                            </button>
                                            <button type="button" className="life-icon-btn is-danger" title="Delete trade" onClick={() => deleteTrade(trade)}>
                                                <Trash2 size={13} />
                                            </button>
                                        </div>
                                    </article>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>

            {editing && (
                <TradeEditor
                    trade={editing}
                    onClose={() => setEditing(null)}
                    onSave={saveTrade}
                    onDelete={deleteTrade}
                />
            )}

            {closing && (
                <CloseTradeDialog
                    trade={closing}
                    onClose={() => setClosing(null)}
                    onSave={closeTrade}
                />
            )}

            {editingBudget && (
                <BudgetEditor
                    budget={budget}
                    error={budgetError}
                    onClose={() => { setBudgetError(''); setEditingBudget(false); }}
                    onSave={saveBudget}
                />
            )}
        </div>
    );
}
