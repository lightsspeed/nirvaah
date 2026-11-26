import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    Plus, Send, Trash2, AlertTriangle, Check, MessageSquare,
    Cloud, Cpu, Brain, X, PanelLeftClose, PanelLeftOpen,
} from 'lucide-react';
import Markdown from './ai/Markdown';
import BrandAiIcon from './BrandAiIcon';

const QUICK_PROMPTS = [
    'Summarise this month',
    'Where am I overspending?',
    "What's left in my budgets?",
    'How are my goals doing?',
    'Show my open tasks',
];

const timeAgo = iso => {
    if (!iso) return '';
    const then = Date.parse(iso.endsWith('Z') ? iso : `${iso}Z`);
    if (!Number.isFinite(then)) return '';
    const mins = Math.max(1, Math.round((Date.now() - then) / 60000));
    if (mins < 60) return `${mins}m ago`;
    if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
    return `${Math.round(mins / 1440)}d ago`;
};

const distinctFails = m => (m.failed || []).filter(f => (f.summary || '').trim() !== String(m.content || '').trim());

function ActionChips({ items }) {
    if (!items || !items.length) return null;
    return (
        <div className="ai-note is-done">
            <strong>{items.length === 1 ? 'Saved to your records' : `${items.length} changes saved`}</strong>
            <ul>{items.map((item, i) => <li key={i}>{item.summary || item.op}</li>)}</ul>
        </div>
    );
}

export default function AssistantPage({ api, user, onChanged }) {
    const [conversations, setConversations] = useState([]);
    const [activeId, setActiveId] = useState('');
    const [messages, setMessages] = useState([]);
    const [memories, setMemories] = useState([]);
    const [status, setStatus] = useState(null);
    const [input, setInput] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(true);
    const [listOpen, setListOpen] = useState(false);
    const bodyRef = useRef(null);
    const fieldRef = useRef(null);

    // Phones show one pane at a time: the conversation list or the thread.
    const isPhone = () => window.matchMedia('(max-width: 900px)').matches;

    const active = useMemo(() => conversations.find(c => c.id === activeId) || null, [conversations, activeId]);

    const refreshConversations = useCallback(async () => {
        const r = await api.get('/chat/conversations');
        setConversations(r.data || []);
        return r.data || [];
    }, [api]);

    const loadConversation = useCallback(async id => {
        if (!id) { setMessages([]); return; }
        const r = await api.get(`/chat/conversations/${id}/messages`);
        setMessages(r.data || []);
    }, [api]);

    useEffect(() => {
        let alive = true;
        (async () => {
            try {
                const [statusRes, memRes, list] = await Promise.all([
                    api.get('/chat/status'),
                    api.get('/chat/memories'),
                    api.get('/chat/conversations'),
                ]);
                if (!alive) return;
                setStatus(statusRes.data);
                setMemories(memRes.data || []);
                setConversations(list.data || []);
                if ((list.data || []).length) {
                    setActiveId(list.data[0].id);
                }
            } catch (err) {
                if (alive) setError(err.response?.data?.detail || 'Could not reach the assistant.');
            } finally {
                if (alive) setLoading(false);
            }
        })();
        return () => { alive = false; };
    }, [api]);

    useEffect(() => {
        if (activeId) loadConversation(activeId).catch(() => setMessages([]));
    }, [activeId, loadConversation]);

    useEffect(() => {
        const el = bodyRef.current;
        if (el && messages.length) el.scrollTop = el.scrollHeight;
    }, [messages, busy]);

    useEffect(() => {
        if (fieldRef.current) fieldRef.current.focus();
    }, [activeId]);

    // Grow the composer with its content; a fixed-height textarea clipped the
    // second line of a longer prompt.
    useEffect(() => {
        const el = fieldRef.current;
        const body = bodyRef.current;
        if (!el) return;
        const pinned = body ? body.scrollHeight - body.scrollTop - body.clientHeight < 40 : false;
        el.style.height = 'auto';
        el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
        // Growing the composer shrinks the log; keep the last message in view.
        if (body && pinned) body.scrollTop = body.scrollHeight;
    }, [input]);

    const startConversation = async () => {
        setError('');
        const r = await api.post('/chat/conversations', {});
        const conv = r.data;
        setConversations(prev => [conv, ...prev]);
        setActiveId(conv.id);
        setMessages([]);
        if (isPhone()) setListOpen(false);
    };

    const removeConversation = async (id, e) => {
        e.stopPropagation();
        await api.delete(`/chat/conversations/${id}`);
        const rest = conversations.filter(c => c.id !== id);
        setConversations(rest);
        if (activeId === id) setActiveId(rest[0]?.id || '');
    };

    const send = async text => {
        const message = String(text ?? input).trim();
        if (!message || busy) return;
        setError('');
        setBusy(true);
        setInput('');

        let conversationId = activeId;
        try {
            if (!conversationId) {
                const created = await api.post('/chat/conversations', {});
                conversationId = created.data.id;
                setConversations(prev => [created.data, ...prev]);
                setActiveId(conversationId);
            }
            setMessages(prev => [...prev, { id: `tmp-${Date.now()}`, role: 'user', content: message }]);
            const r = await api.post(`/chat/conversations/${conversationId}/messages`, { message });
            setMessages(prev => [...prev, r.data]);
            if ((r.data.applied || []).length) {
                if (onChanged) onChanged();
                const mem = await api.get('/chat/memories');
                setMemories(mem.data || []);
            }
            refreshConversations().catch(() => {});
        } catch (err) {
            const detail = err.response?.data?.detail;
            setError(typeof detail === 'string' ? detail : 'The assistant is not reachable right now.');
        } finally {
            setBusy(false);
        }
    };

    const resolvePending = async (messageId, actions, mode) => {
        if (busy) return;
        if (mode === 'keep') {
            setMessages(prev => prev.map(m => (m.id === messageId ? { ...m, pending: [], kept: true } : m)));
            return;
        }
        setBusy(true);
        setError('');
        try {
            const r = await api.post(`/chat/conversations/${activeId}/confirm`, { actions });
            const applied = r.data?.applied || [];
            const failed = r.data?.failed || [];
            setMessages(prev => prev.map(m => {
                if (m.id !== messageId) return m;
                const stale = /confirm below|i can remove/i.test(m.content || '');
                return {
                    ...m,
                    content: stale && applied.length ? 'Done.' : m.content,
                    pending: [],
                    applied: [...(m.applied || []), ...applied],
                    failed: [...(m.failed || []), ...failed],
                };
            }));
            if (applied.length && onChanged) onChanged();
        } catch {
            setError('Could not apply that change. Nothing was removed.');
        } finally {
            setBusy(false);
        }
    };

    const addMemory = async fact => {
        const r = await api.post('/chat/memories', { fact });
        setMemories(prev => [r.data, ...prev]);
    };

    const removeMemory = async id => {
        await api.delete(`/chat/memories/${id}`);
        setMemories(prev => prev.filter(m => m.id !== id));
    };

    const onKeyDown = e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    };

    const localUp = status?.local?.reachable;
    const cloudReady = status?.fallback?.enabled;
    const providerBadge = (m) => {
        if (m.role !== 'assistant' || !m.provider) return null;
        const isCloud = m.provider === 'cloud';
        return (
            <span className={`ai-prov ${isCloud ? 'is-cloud' : 'is-local'}`} title={isCloud ? 'Answered by the cloud fallback' : 'Answered by the local model'}>
                {isCloud ? <Cloud size={12} /> : <Cpu size={12} />}
                {isCloud ? 'deepseek' : 'local'}
            </span>
        );
    };

    return (
        <div className={`ai-page${listOpen ? '' : ' is-collapsed'}`}>
            <aside className="ai-rail">
                <div className="ai-rail-head">
                    <button type="button" className="ai-new" onClick={startConversation}>
                        <Plus size={16} /> New conversation
                    </button>
                    <button
                        type="button"
                        className="ai-rail-toggle"
                        onClick={() => setListOpen(false)}
                        title="Hide conversations"
                    >
                        <PanelLeftClose size={16} />
                    </button>
                </div>

                <div className="ai-rail-scroll">
                    <small className="ai-rail-label">Conversations</small>
                    {conversations.length === 0 && <p className="ai-rail-empty">No conversations yet.</p>}
                    <ul className="ai-convs">
                        {conversations.map(conv => (
                            <li key={conv.id}>
                                <button
                                    type="button"
                                    className={`ai-conv${conv.id === activeId ? ' is-active' : ''}`}
                                    onClick={() => {
                                        setActiveId(conv.id);
                                        if (isPhone()) setListOpen(false);
                                    }}
                                >
                                    <MessageSquare size={14} />
                                    <span>
                                        <b>{conv.title}</b>
                                        <small>{conv.messages} messages · {timeAgo(conv.updated_at)}</small>
                                    </span>
                                </button>
                                <button type="button" className="ai-conv-del" title="Delete conversation" onClick={e => removeConversation(conv.id, e)}>
                                    <Trash2 size={13} />
                                </button>
                            </li>
                        ))}
                    </ul>

                    <small className="ai-rail-label"><Brain size={12} /> Memory</small>
                    {memories.length === 0 && (
                        <p className="ai-rail-empty">Say “remember that…” and it sticks across conversations.</p>
                    )}
                    <ul className="ai-memories">
                        {memories.map(mem => (
                            <li key={mem.id}>
                                <span>{mem.fact}</span>
                                <button type="button" title="Forget this" onClick={() => removeMemory(mem.id)}><X size={12} /></button>
                            </li>
                        ))}
                    </ul>
                    <form
                        className="ai-memory-add"
                        onSubmit={e => { e.preventDefault(); const v = e.target.elements.fact.value.trim(); if (v) { addMemory(v); e.target.reset(); } }}
                    >
                        <input name="fact" placeholder="Add a fact to remember…" maxLength={200} />
                    </form>

                </div>

                <div className="ai-rail-foot">
                    <span className={`ai-dot ${cloudReady ? 'is-cloud' : 'is-down'}`} />
                    <span>{cloudReady ? `deepseek-flash · DeepSeek` : 'DeepSeek key missing'}</span>
                </div>
            </aside>

            <section className="ai-thread">
                <header className="ai-thread-head">
                    {!listOpen && (
                        <button type="button" className="ai-rail-toggle" onClick={() => setListOpen(true)} title="Show conversations">
                            <PanelLeftOpen size={16} />
                        </button>
                    )}
                    <div>
                        <h3>{active?.title || 'New conversation'}</h3>
                        <small>
                            {active ? `${active.messages} messages` : 'Ask about your records, or tell me what to change'}
                        </small>
                    </div>
                    <button
                        type="button"
                        className="ai-new-mini"
                        onClick={startConversation}
                        title="New conversation"
                        aria-label="New conversation"
                    >
                        <Plus size={16} />
                    </button>
                    <span className="ai-thread-tag">
                        <BrandAiIcon size={14} />
                        deepseek-flash
                    </span>
                </header>

                <div className="ai-thread-body" ref={bodyRef}>
                    {loading && <p className="ai-thread-empty">Loading…</p>}

                    {!loading && messages.length === 0 && (
                        <div className="ai-empty">
                            <h4>Ask about your money.</h4>
                            <p>
                                I can read your transactions, budgets, goals, investments,
                                notes, tasks and journal — and add, change or remove records when you ask.
                                Follow-ups work: “and last month?”, “delete that one”.
                            </p>
                            <div className="ai-quick">
                                {QUICK_PROMPTS.map(p => (
                                    <button key={p} type="button" onClick={() => send(p)}>{p}</button>
                                ))}
                            </div>
                        </div>
                    )}

                    {messages.map(m => (
                        <div key={m.id} className={`ai-msg ${m.role === 'user' ? 'is-user' : 'is-bot'}`}>
                            <span className="ai-who">
                                {m.role === 'user' ? (user?.name?.split(' ')[0] || 'You') : 'Nirvaah'}
                                {providerBadge(m)}
                            </span>
                            <div className="ai-bubble"><Markdown text={m.content} /></div>
                            <ActionChips items={m.applied} />
                            {(m.failed || []).length > 0 && distinctFails(m).length > 0 && (
                                <div className="ai-note is-fail">
                                    <AlertTriangle size={15} />
                                    <ul>{distinctFails(m).map((f, k) => <li key={k}>{f.summary || f.error || f.op}</li>)}</ul>
                                </div>
                            )}
                            {(m.pending || []).length > 0 && (
                                <div className="ai-note is-confirm">
                                    <strong>Confirm removal</strong>
                                    <ul>{m.pending.map((p, k) => <li key={k}>{p.summary}</li>)}</ul>
                                    <span className="ai-hint">Nothing is removed until you tap Delete.</span>
                                    <div className="ai-confirm-row">
                                        <button type="button" className="ai-btn is-danger" disabled={busy} onClick={() => resolvePending(m.id, m.pending, 'apply')}>
                                            <Trash2 size={14} /> Delete
                                        </button>
                                        <button type="button" className="ai-btn is-quiet" disabled={busy} onClick={() => resolvePending(m.id, m.pending, 'keep')}>
                                            Keep it
                                        </button>
                                    </div>
                                </div>
                            )}
                            {m.kept && (m.applied || []).length === 0 && (
                                <div className="ai-note"><Check size={15} /> Kept — nothing was deleted.</div>
                            )}
                            {m.note && <p className="ai-degraded">{m.note}</p>}
                        </div>
                    ))}

                    {busy && (
                        <div className="ai-msg is-bot">
                            <span className="ai-who">Nirvaah</span>
                            <div className="ai-bubble ai-typing"><i /><i /><i /></div>
                        </div>
                    )}
                </div>

                {error && <div className="ai-error">{error}</div>}

                <div className="ai-composer">
                    <textarea
                        ref={fieldRef}
                        rows={1}
                        placeholder={active ? 'Ask a follow-up, or say what to change…' : 'Ask, or say what to change…'}
                        value={input}
                        onChange={e => setInput(e.target.value)}
                        onKeyDown={onKeyDown}
                        aria-label="Message Nirvaah"
                        enterKeyHint="send"
                    />
                    <button type="button" className="ai-send" disabled={busy || !input.trim()} onClick={() => send()} title="Send" aria-label="Send message">
                        <Send size={17} />
                    </button>
                </div>
            </section>
        </div>
    );
}
