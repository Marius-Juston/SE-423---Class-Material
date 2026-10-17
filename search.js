// Search across lecture slides and image descriptions, and the figure gallery.
//
// Both read search-index.json (built by tools/a11y/search_index.py in CI): every
// lecture slide (title + text) and every described image (slide pictures, homework
// and lab images, TikZ figures) with a thumbnail, its full alt text and where it is.
// Everything is built with DOM methods and textContent, never innerHTML.
(() => {
    'use strict';

    const PAGE = 12;           // results shown before "Show all"
    let indexPromise = null;

    function loadIndex() {
        indexPromise ||= fetch('search-index.json')
            .then(r => (r.ok ? r.json() : { entries: [] }))
            .then(d => d.entries || [])
            .catch(() => []);
        return indexPromise;
    }

    const norm = s => (s || '').toLowerCase();
    const termsOf = q => norm(q).split(/\s+/).filter(t => t.length > 1);

    function haystack(e) {
        return norm(e.kind === 'image' ? `${e.alt} ${e.title} ${e.where}` : `${e.title} ${e.text} ${e.where}`);
    }

    function el(tag, props = {}, ...children) {
        const node = document.createElement(tag);
        for (const [k, v] of Object.entries(props)) {
            if (v === undefined || v === null || v === false) continue;
            if (k === 'class') node.className = v;
            else if (k === 'text') node.textContent = v;
            else node.setAttribute(k, v === true ? '' : v);
        }
        for (const c of children) if (c) node.append(c);
        return node;
    }

    // Text with every search term wrapped in <mark> (built as text nodes).
    function highlighted(text, terms) {
        const frag = document.createDocumentFragment();
        if (!terms.length) { frag.append(text); return frag; }
        const escaped = terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
        const re = new RegExp(`(${escaped.join('|')})`, 'gi');
        let last = 0;
        for (const m of text.matchAll(re)) {
            frag.append(text.slice(last, m.index), el('mark', { text: m[0] }));
            last = m.index + m[0].length;
        }
        frag.append(text.slice(last));
        return frag;
    }

    // The part of a long text around its first match.
    function excerpt(text, terms, size = 220) {
        if (!text || text.length <= size) return text || '';
        const lower = norm(text);
        const at = Math.min(...terms.map(t => lower.indexOf(t)).filter(i => i >= 0), text.length);
        const start = Math.max(0, Math.min(at - 60, text.length - size));
        return (start > 0 ? '… ' : '') + text.slice(start, start + size).trim() + (start + size < text.length ? ' …' : '');
    }

    const FORMAT_LABEL = { svg: 'SVG', png: 'PNG', jpg: 'JPEG', gif: 'GIF', webp: 'WebP', diagram: 'Diagram' };

    // One figure: thumbnail (link to the full image), where it is, its description.
    function imageCard(e, terms, idPrefix) {
        const capId = `${idPrefix}-${e.id}`;
        const thumb = e.thumb
            ? el('a', { href: e.full || e.thumb, class: 'fig-thumb', target: '_blank', 'aria-describedby': capId },
                el('img', { src: e.thumb, alt: '', loading: 'lazy', decoding: 'async' }),
                el('span', { class: 'sr-only', text: `Full-size image: ${e.title} (opens in a new tab)` }))
            : el('div', { class: 'fig-thumb fig-none', text: 'Diagram drawn in the document' });
        const linkText = e.group === 'lecture'
            ? (e.link.includes('#s') ? 'Open the slide' : 'Open the figure')
            : 'Open the document';
        return el('li', { class: 'fig-card' },
            el('figure', {},
                thumb,
                el('figcaption', { id: capId },
                    el('p', { class: 'fig-where', text: `${e.title} · ${FORMAT_LABEL[e.format] || e.format}` }),
                    el('p', { class: 'fig-alt' }, highlighted(e.alt, terms)),
                    el('p', { class: 'fig-links' },
                        el('a', { href: e.link, target: '_blank', text: linkText },
                            el('span', { class: 'sr-only', text: ' (opens in a new tab)' }))))));
    }

    function slideItem(e, terms) {
        return el('li', { class: 'slide-hit' },
            el('a', { href: e.link, target: '_blank' },
                el('span', { class: 'slide-where', text: `${e.where}: ` }), highlighted(e.title, terms),
                el('span', { class: 'sr-only', text: ' (opens in a new tab)' })),
            e.text ? el('p', {}, highlighted(excerpt(e.text, terms), terms)) : null);
    }

    // A list that shows PAGE items and a "Show all" button for the rest.
    function pagedList(items, listClass, render) {
        const list = el('ul', { class: listClass, role: 'list' });
        items.slice(0, PAGE).forEach(i => list.append(render(i)));
        const frag = document.createDocumentFragment();
        frag.append(list);
        if (items.length > PAGE) {
            const more = el('button', { type: 'button', class: 'show-all', text: `Show all ${items.length}` });
            more.addEventListener('click', () => {
                items.slice(PAGE).forEach(i => list.append(render(i)));
                more.remove();
                list.children[PAGE]?.querySelector('a')?.focus();
            });
            frag.append(more);
        }
        return frag;
    }

    // ------------------------------------------------------------ header search
    let lastQuery = '';
    async function updateSearch(query, cardsShown, cardsTotal) {
        lastQuery = query;
        const section = document.getElementById('search-results');
        const status = document.getElementById('search-status');
        const terms = termsOf(query);
        if (!terms.length) {
            section.hidden = true;
            status.textContent = '';
            return;
        }
        const entries = await loadIndex();
        if (query !== lastQuery) return; // a newer query is running
        const hits = entries.filter(e => { const h = haystack(e); return terms.every(t => h.includes(t)); });
        const slides = hits.filter(e => e.kind === 'slide');
        const images = hits.filter(e => e.kind === 'image');
        const body = document.getElementById('search-results-body');
        body.replaceChildren();
        document.getElementById('search-results-query').textContent = query.trim();
        if (slides.length) {
            body.append(el('h3', { text: `Lecture slides (${slides.length})` }),
                pagedList(slides, 'slide-hits', e => slideItem(e, terms)));
        }
        if (images.length) {
            body.append(el('h3', { text: `Figures and images (${images.length})` }),
                pagedList(images, 'fig-grid', e => imageCard(e, terms, 'sr')));
        }
        if (!slides.length && !images.length) {
            body.append(el('p', { text: 'No slides or figures match.' }));
        }
        section.hidden = false;
        status.textContent = `${cardsShown} of ${cardsTotal} course items, ${slides.length} slides and ${images.length} figures match`;
    }

    // ------------------------------------------------------------ gallery
    async function renderGallery() {
        const grid = document.getElementById('gallery-grid');
        const status = document.getElementById('gallery-status');
        let entries = (await loadIndex()).filter(e => e.kind === 'image');
        if (!entries.length && window.SE423_FALLBACK_FIGURES) entries = window.SE423_FALLBACK_FIGURES;
        const group = document.getElementById('gallery-source').value;
        const format = document.getElementById('gallery-format').value;
        const terms = termsOf(document.getElementById('gallery-filter').value);
        const shown = entries.filter(e =>
            (group === 'all' || e.group === group) &&
            (format === 'all' || e.format === format) &&
            terms.every(t => haystack(e).includes(t)));
        grid.replaceChildren(pagedList(shown, 'fig-grid', e => imageCard(e, terms, 'gal')));
        status.textContent = `${shown.length} of ${entries.length} figures shown`;
    }

    window.SE423Search = { update: updateSearch, renderGallery };

    document.addEventListener('DOMContentLoaded', () => {
        ['gallery-source', 'gallery-format'].forEach(id =>
            document.getElementById(id)?.addEventListener('change', renderGallery));
        let t;
        document.getElementById('gallery-filter')?.addEventListener('input', () => {
            clearTimeout(t);
            t = setTimeout(renderGallery, 250);
        });
    });
})();
