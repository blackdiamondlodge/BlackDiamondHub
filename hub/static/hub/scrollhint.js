/* A bouncing "more below" chevron on everything that can scroll down.
 *
 * Finds scrollers by itself (the page and any overflow-y:auto|scroll box), so
 * apps get it without doing anything. The chevron hides at the end of the
 * content and while something (a dialog, the keyboard, the screensaver)
 * covers the bottom of the scroller.
 *
 *   data-scroll-hint="off"   on a scroller or an ancestor: no chevron there
 *                            (on <body>: none on the whole page)
 *   --hub-scroll-hint-bg     colour the fade ends in (default: the background
 *   --hub-scroll-hint-fg     behind the scroller) / the chevron colour
 *   window.hubScrollHint.refresh()   rescan now, e.g. after swapping content
 */
(function () {
    var SLACK = 8, MIN_H = 120, MIN_W = 160;
    var SKIP = { TEXTAREA: 1, SELECT: 1, INPUT: 1, IFRAME: 1, VIDEO: 1, CANVAS: 1 };
    var hints = new Map();  // scroller -> hint element
    var queued = false;

    function isPage(el) { return el === document.body || el === document.documentElement; }

    function overflows(el) { return el.scrollHeight - el.clientHeight > SLACK; }

    function pageScroller() {
        var b = document.body, h = document.documentElement;
        if (b.getAttribute('data-scroll-hint') === 'off') return null;
        var by = getComputedStyle(b).overflowY, hy = getComputedStyle(h).overflowY;
        if ((by === 'auto' || by === 'scroll') && hy !== 'visible' && overflows(b)) return b;
        if (hy !== 'hidden' && !(hy === 'visible' && by === 'hidden') && overflows(h)) return h;
        return null;
    }

    function innerScrollers() {
        var out = [], all = document.body.getElementsByTagName('*');
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            if (SKIP[el.tagName] || el.classList.contains('hub-scroll-hint')) continue;
            if (el.clientHeight < MIN_H || el.clientWidth < MIN_W || !overflows(el)) continue;
            var oy = getComputedStyle(el).overflowY;
            if (oy !== 'auto' && oy !== 'scroll') continue;
            if (el.closest('[data-scroll-hint="off"]')) continue;
            out.push(el);
        }
        return out;
    }

    function rgb(s) {
        var m = (s || '').match(/[\d.]+/g);
        return m && m.length >= 3 ? m.map(Number) : null;
    }

    // The solid colour behind el, or null over an image/gradient.
    function backdrop(el) {
        for (var n = el; n && n.nodeType === 1; n = n.parentElement) {
            var cs = getComputedStyle(n);
            if (cs.backgroundImage !== 'none') return null;
            var c = rgb(cs.backgroundColor);
            if (c && (c.length < 4 || c[3] >= 0.9)) return c;
        }
        return null;
    }

    function make(el) {
        var hint = document.createElement('div');
        hint.className = 'hub-scroll-hint';
        hint.setAttribute('aria-hidden', 'true');
        hint.innerHTML = '<i class="fas fa-chevron-down"></i>';
        var cs = getComputedStyle(el);
        var bg = cs.getPropertyValue('--hub-scroll-hint-bg').trim();
        var fg = cs.getPropertyValue('--hub-scroll-hint-fg').trim();
        if (!bg) {
            var c = backdrop(isPage(el) ? document.body : el);
            if (c) {
                bg = 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')';
                if (!fg && 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2] > 150) fg = 'rgba(0,0,0,.45)';
            }
        }
        if (bg) hint.style.setProperty('--hub-scroll-hint-bg', bg);
        if (fg) hint.style.setProperty('--hub-scroll-hint-fg', fg);
        // A sibling shares the scroller's stacking context, so a scroller in a
        // dialog gets its chevron above the dialog rather than under it.
        (isPage(el) ? document.body : el.parentNode).appendChild(hint);
        return hint;
    }

    function covered(el, x, y) {
        var hit = document.elementFromPoint(x, y);
        if (!hit) return true;
        if (!isPage(el)) return !(hit === el || el.contains(hit));
        if (document.body.classList.contains('modal-open') || document.querySelector('dialog:modal')) return true;
        for (var n = hit; n && n !== document.body; n = n.parentElement) {
            if (getComputedStyle(n).position !== 'fixed') continue;
            var b = n.getBoundingClientRect();
            if (b.height >= 200 && b.width >= window.innerWidth / 2) return true;
        }
        return false;
    }

    function place(el, hint) {
        var vw = window.innerWidth, vh = window.innerHeight, left, right, top, bottom;
        if (isPage(el)) {
            left = 0; right = vw; top = 0; bottom = vh;
        } else {
            var r = el.getBoundingClientRect();
            left = r.left + el.clientLeft; right = left + el.clientWidth;
            top = r.top + el.clientTop; bottom = top + el.clientHeight;
            // Bottom off screen: the page's own chevron covers it.
            if (bottom > vh + 1 || bottom - Math.max(top, 0) < 60) return false;
            left = Math.max(left, 0); right = Math.min(right, vw); top = Math.max(top, 0);
        }
        var small = bottom - top < 300, h = small ? 48 : 80;
        var s = hint.style;
        s.left = left + 'px'; s.top = (bottom - h) + 'px'; s.width = (right - left) + 'px'; s.height = h + 'px';
        hint.classList.toggle('small', small);
        // position:fixed is relative to a transformed ancestor, if there is one.
        var got = hint.getBoundingClientRect();
        if (Math.abs(got.left - left) > 1 || Math.abs(got.top - (bottom - h)) > 1) {
            s.left = (2 * left - got.left) + 'px';
            s.top = (2 * (bottom - h) - got.top) + 'px';
        }
        return !covered(el, (left + right) / 2, bottom - 10);
    }

    function update() {
        queued = false;
        hints.forEach(function (hint, el) {
            var more = el.scrollHeight - el.clientHeight - el.scrollTop > SLACK;
            hint.classList.toggle('on', more && place(el, hint));
        });
    }

    function schedule() {
        if (!queued) { queued = true; requestAnimationFrame(update); }
    }

    function scan() {
        if (!document.body || document.hidden) return;
        var want = innerScrollers(), page = pageScroller();
        if (page) want.push(page);
        hints.forEach(function (hint, el) {
            if (want.indexOf(el) < 0 || !hint.isConnected) { hint.remove(); hints.delete(el); }
        });
        want.forEach(function (el) { if (!hints.has(el)) hints.set(el, make(el)); });
        update();
    }

    document.addEventListener('scroll', schedule, true);
    document.addEventListener('transitionend', schedule, true);
    window.addEventListener('resize', scan);
    window.addEventListener('load', scan);
    document.addEventListener('visibilitychange', scan);
    if (document.readyState !== 'loading') scan();
    else document.addEventListener('DOMContentLoaded', scan);
    setInterval(scan, 1000);

    window.hubScrollHint = { refresh: scan };
})();
