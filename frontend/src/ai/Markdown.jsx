import React from 'react';

/* Tiny markdown for assistant replies: **bold**, `code`, "- " bullets,
   blank-line paragraphs. A full parser would be a dependency for four features. */

function inline(text, keyPrefix) {
    const nodes = [];
    const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
    let last = 0;
    let match;
    let i = 0;
    while ((match = pattern.exec(text)) !== null) {
        if (match.index > last) nodes.push(text.slice(last, match.index));
        const token = match[0];
        if (token.startsWith('**')) nodes.push(<strong key={`${keyPrefix}-b${i}`}>{token.slice(2, -2)}</strong>);
        else nodes.push(<code key={`${keyPrefix}-c${i}`}>{token.slice(1, -1)}</code>);
        last = match.index + token.length;
        i += 1;
    }
    if (last < text.length) nodes.push(text.slice(last));
    return nodes;
}

export default function Markdown({ text }) {
    const blocks = [];
    let bullets = [];
    let paragraph = [];

    const flushParagraph = () => {
        if (!paragraph.length) return;
        blocks.push(<p key={`p${blocks.length}`}>{inline(paragraph.join(' '), `p${blocks.length}`)}</p>);
        paragraph = [];
    };
    const flushBullets = () => {
        if (!bullets.length) return;
        blocks.push(
            <ul key={`u${blocks.length}`}>
                {bullets.map((item, idx) => <li key={idx}>{inline(item, `u${blocks.length}-${idx}`)}</li>)}
            </ul>
        );
        bullets = [];
    };

    String(text || '').split('\n').forEach(raw => {
        const line = raw.trim();
        if (!line) { flushParagraph(); flushBullets(); return; }
        const bullet = line.match(/^[-*•]\s+(.*)$/);
        if (bullet) { flushParagraph(); bullets.push(bullet[1]); return; }
        flushBullets();
        paragraph.push(line);
    });
    flushParagraph();
    flushBullets();

    return blocks.length ? <>{blocks}</> : <p>{String(text || '')}</p>;
}
