import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown } from 'lucide-react';

// The app's one dropdown: a neutral trigger and a viewport-anchored menu.

export default function CustomSelect({
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
