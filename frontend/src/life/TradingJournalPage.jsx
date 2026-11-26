import React, { useMemo, useState } from 'react';
import {
    Plus, Trash2, Pencil, Check, TrendingUp, TrendingDown, Activity, Target, ArrowUpRight, ArrowDownLeft,
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

const blankTrade = () => ({
    id: uid(),
    trade_date: todayISO(),
    symbol: '',
    side: 'buy',
    quantity: '',
    entry_price: '',
    exit_price: '',
    fees: '0',
    setup: '',
    notes: '',
    createdAt: Date.now(),
    updatedAt: Date.now(),
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
            subtitle={isNew ? 'JOURNAL ENTRY' : `${formatDay(trade.trade_date).toUpperCase()}`}
            onClose={onClose}
            wide
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
                            autoFocus={isNew}
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

                <div className="trade-form-grid is-three">
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
                </div>

                <label className="life-field">
                    <span className="life-field-label">Setup / strategy</span>
                    <input
                        className="life-input"
                        placeholder="Breakout, pullback, news, range…"
                        value={draft.setup}
                        onChange={e => setDraft({ ...draft, setup: e.target.value })}
                    />
                </label>

                <label className="life-field">
                    <span className="life-field-label">Notes</span>
                    <textarea
                        className="life-textarea"
                        rows={4}
                        placeholder="What did you see, what did you learn, what would you repeat?"
                        value={draft.notes}
                        onChange={e => setDraft({ ...draft, notes: e.target.value })}
                    />
                </label>

                {error && <div className="trade-form-error" role="alert">{error}</div>}
            </form>
        </Modal>
    );
}

export default function TradingJournalPage() {
    const { ask, dialog } = useConfirm();
    const [trades, setTrades] = useCollection(TRADES_KEY);
    const [filter, setFilter] = useState('all');
    const [editing, setEditing] = useState(null);

    const stats = useMemo(() => {
        const closed = trades
            .map(trade => ({ trade, pnl: pnlOf(trade) }))
            .filter(row => row.pnl !== null);
        const wins = closed.filter(row => row.pnl > 0).length;
        const net = closed.reduce((sum, row) => sum + row.pnl, 0);
        const open = trades.length - closed.length;
        return {
            closed: closed.length,
            open,
            wins,
            winRate: closed.length ? Math.round((wins / closed.length) * 100) : 0,
            net,
        };
    }, [trades]);

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
    };

    return (
        <div className="life-page trading-page">
            {dialog}
            <PageHero>
                <button type="button" className="life-btn is-primary" onClick={() => setEditing(blankTrade())} aria-label="New trade">
                    <Plus size={15} /><span className="life-btn-label">New trade</span>
                </button>
            </PageHero>

            <div className="trade-intro">
                <span className="trade-intro-mark"><Activity size={15} /></span>
                <p><b>Journal only.</b> Trades never touch balances, budgets or reports — they are here to make your process visible.</p>
            </div>

            <div className="life-stats">
                <StatTile label="Closed trades" value={stats.closed} hint="With an exit price" icon={Check} tint="#6a9bd0" />
                <StatTile label="Win rate" value={`${stats.winRate}%`} hint={`${stats.wins || 0} winners`} icon={Target} tint="#7fa650" />
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
                                ? 'Log the setup, the entry and the exit. The journal is for process, not for your ledger.'
                                : 'Try another filter, or log a new trade.'}
                            action={filter === 'all' && (
                                <button type="button" className="life-btn is-primary" onClick={() => setEditing(blankTrade())}>
                                    <Plus size={14} /> Log a trade
                                </button>
                            )}
                        />
                    ) : (
                        <div className="trades-grid">
                            {visible.map(trade => {
                                const pnl = pnlOf(trade);
                                const win = pnl !== null && pnl > 0;
                                const loss = pnl !== null && pnl < 0;
                                return (
                                    <article className={`trade-card${win ? ' is-win' : loss ? ' is-loss' : ''}`} key={trade.id}>
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
                                        <div className="trade-actions">
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
        </div>
    );
}
