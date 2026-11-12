/* On-screen keyboard for the hub's own wall display.
 *
 * Only runs on the hub screen: a wide touch-only device (coarse pointer, no
 * hover). Override with localStorage 'hub-kb' = 'on' | 'off'.
 */
(function () {
    'use strict';

    function enabled() {
        let pref = null;
        try { pref = localStorage.getItem('hub-kb'); } catch (e) { /* private mode */ }
        if (pref === 'on') return true;
        if (pref === 'off') return false;
        const mq = (q) => window.matchMedia && window.matchMedia(q).matches;
        return window.innerWidth >= 1280 && mq('(any-pointer: coarse)') && !mq('(any-hover: hover)');
    }
    if (!enabled()) return;

    const TYPES = ['text', 'password', 'email', 'search', 'url', 'number', 'tel'];
    const LETTERS = ['1234567890', 'qwertyuiop', 'asdfghjkl', 'zxcvbnm'];
    const SYMBOLS = ['1234567890', '!@#$%^&*()', '-_=+/\\|:;~', '[]{}<>\'"?'];

    let kb, chip, showBtn, keys;
    let field = null, page = 'abc', shift = false, caps = false, lastShift = 0;
    let repeat = null, pressed = null;

    function eligible(el) {
        if (!el || el.disabled || el.readOnly || el.closest('[data-no-kb]')) return false;
        if (el.tagName === 'TEXTAREA') return true;
        if (el.tagName !== 'INPUT') return false;
        return TYPES.includes((el.dataset.kbType || el.getAttribute('type') || 'text').toLowerCase());
    }

    function kind(el) {
        const t = (el.dataset.kbType || el.getAttribute('type') || 'text').toLowerCase();
        if (t === 'number' || t === 'tel') return 'num';
        return t;
    }

    function suppressNative(el) {
        if (!el.hasAttribute('data-kb-im')) {
            el.setAttribute('data-kb-im', el.getAttribute('inputmode') || '');
            el.setAttribute('inputmode', 'none');
        }
    }

    function label(el) {
        if (el.id) {
            const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
            if (l && l.textContent.trim()) return l.textContent.trim();
        }
        return el.getAttribute('aria-label') || el.placeholder || el.name || 'text';
    }

    function fields(form) {
        return Array.from(form.elements).filter((el) => eligible(el) && el.type !== 'hidden' && el.offsetParent !== null);
    }

    function nextField(el) {
        if (!el.form) return null;
        const list = fields(el.form);
        return list[list.indexOf(el) + 1] || null;
    }

    function enterLabel(el) {
        if (el.tagName === 'TEXTAREA') return '↵';
        if (nextField(el)) return 'Next';
        const btn = el.form && el.form.querySelector('button[type=submit], input[type=submit], button:not([type])');
        const txt = btn && (btn.textContent || btn.value || '').trim();
        if (txt && txt.length <= 12) return txt;
        return el.form ? 'Submit' : 'Done';
    }

    // ---- editing -------------------------------------------------------

    function caret(el) {
        try {
            if (el.selectionStart !== null) return [el.selectionStart, el.selectionEnd];
        } catch (e) { /* email/number inputs have no selection API */ }
        return null;
    }

    function setCaret(el, pos) {
        try { el.setSelectionRange(pos, pos); } catch (e) { /* unsupported type */ }
    }

    function changed(el) {
        el.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function insert(text) {
        const el = field;
        if (!el) return;
        const v = el.value, c = caret(el);
        if (c) {
            el.value = v.slice(0, c[0]) + text + v.slice(c[1]);
            setCaret(el, c[0] + text.length);
        } else {
            el.value = v + text;
        }
        changed(el);
    }

    function backspace() {
        const el = field;
        if (!el) return;
        const v = el.value, c = caret(el);
        if (c) {
            const start = c[0] === c[1] ? Math.max(0, c[0] - 1) : c[0];
            if (start === c[1]) return;
            el.value = v.slice(0, start) + v.slice(c[1]);
            setCaret(el, start);
        } else {
            if (!v) return;
            el.value = v.slice(0, -1);
        }
        changed(el);
    }

    function enter() {
        const el = field;
        if (!el) return;
        if (el.tagName === 'TEXTAREA') { insert('\n'); return; }
        const next = nextField(el);
        if (next) { next.focus(); open(next); return; }
        const opts = { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true };
        const ok = el.dispatchEvent(new KeyboardEvent('keydown', opts));
        el.dispatchEvent(new KeyboardEvent('keyup', opts));
        const form = el.form;
        close();
        if (ok && form) {
            if (form.requestSubmit) form.requestSubmit(); else form.submit();
        }
    }

    // ---- rendering -----------------------------------------------------

    function key(cls, text, act, ch) {
        const b = document.createElement('div');
        b.className = 'hub-kb-key ' + cls;
        b.textContent = text;
        b.dataset.act = act;
        if (ch !== undefined) { b.dataset.c = ch; b.classList.add('ch'); }
        return b;
    }

    function row(items) {
        const r = document.createElement('div');
        r.className = 'hub-kb-row';
        items.forEach((i) => r.appendChild(i));
        return r;
    }

    function gap() {
        const g = document.createElement('div');
        g.className = 'hub-kb-gap';
        return g;
    }

    function chars(s, upper) {
        return Array.from(s).map((c) => {
            const out = upper ? c.toUpperCase() : c;
            return key('', out, 'ch', out);
        });
    }

    function render() {
        const k = kind(field);
        keys.innerHTML = '';
        keys.classList.toggle('num', k === 'num');
        if (k === 'num') {
            ['123', '456', '789'].forEach((r) => keys.appendChild(row(chars(r))));
            keys.appendChild(row([key('fn', '⌫', 'bs'), key('', '0', 'ch', '0'), key('go', 'Done', 'done')]));
            return;
        }
        const up = shift || caps;
        const L = page === 'abc' ? LETTERS : SYMBOLS;
        keys.appendChild(row(chars(L[0])));
        keys.appendChild(row(chars(L[1], up && page === 'abc')));
        if (page === 'abc') {
            keys.appendChild(row([gap()].concat(chars(L[2], up), [gap()])));
            const sh = key('fn w15' + (up ? ' on' : '') + (caps ? ' lock' : ''), '⇧', 'shift');
            keys.appendChild(row([sh].concat(chars(L[3], up), [key('fn w15', '⌫', 'bs')])));
        } else {
            keys.appendChild(row(chars(L[2])));
            keys.appendChild(row(chars(L[3]).concat([key('fn w15', '⌫', 'bs')])));
        }
        const email = k === 'email';
        const bottom = [
            key('fn w15', page === 'abc' ? '#+=' : 'ABC', 'page'),
            email ? key('', '@', 'ch', '@') : key('', ',', 'ch', ','),
            key('sp', 'space', 'ch', ' '),
            key('', '.', 'ch', '.'),
        ];
        if (email) bottom.push(key('fn w15', '.com', 'ch', '.com'));
        bottom.push(key('go w2', enterLabel(field), 'enter'));
        keys.appendChild(row(bottom));
    }

    function build() {
        kb = document.createElement('div');
        kb.className = 'hub-kb';
        kb.setAttribute('role', 'group');
        kb.setAttribute('aria-label', 'On-screen keyboard');
        kb.innerHTML =
            '<div class="hub-kb-bar"><div class="t">⌨ Typing in <span class="hub-kb-chip"></span></div>' +
            '<div class="t"><button type="button" class="hub-kb-show" data-act="show">👁 Show password</button>' +
            '<button type="button" class="hub-kb-hide" data-act="hide">Hide ⌄</button></div></div>' +
            '<div class="hub-kb-keys"></div>';
        chip = kb.querySelector('.hub-kb-chip');
        showBtn = kb.querySelector('.hub-kb-show');
        keys = kb.querySelector('.hub-kb-keys');
        document.body.appendChild(kb);

        // Keep focus (and the caret) in the field while keys are tapped.
        kb.addEventListener('pointerdown', onPress);
        kb.addEventListener('mousedown', (e) => e.preventDefault());
        ['pointerup', 'pointercancel', 'pointerleave'].forEach((t) => kb.addEventListener(t, release));
    }

    function onPress(e) {
        e.preventDefault();
        const t = e.target.closest('[data-act]');
        if (!t || !field) return;
        const act = t.dataset.act;
        if (t.classList.contains('hub-kb-key')) {
            release();
            pressed = t;
            t.classList.add('press');
        }
        if (act === 'ch') {
            insert(t.dataset.c);
            if (shift && !caps) { shift = false; render(); }
        } else if (act === 'bs') {
            backspace();
            repeat = setTimeout(function rep() { backspace(); repeat = setTimeout(rep, 70); }, 450);
        } else if (act === 'shift') {
            const now = Date.now();
            if (caps) { caps = false; shift = false; }
            else if (shift && now - lastShift < 400) { caps = true; }
            else { shift = !shift; }
            lastShift = now;
            render();
        } else if (act === 'page') {
            page = page === 'abc' ? 'sym' : 'abc';
            render();
        } else if (act === 'enter') {
            enter();
        } else if (act === 'done' || act === 'hide') {
            const el = field;
            close();
            if (el) el.blur();
        } else if (act === 'show') {
            const pw = field.getAttribute('type') === 'password';
            field.setAttribute('type', pw ? 'text' : 'password');
            showBtn.classList.toggle('on', pw);
            showBtn.textContent = pw ? '👁 Hide password' : '👁 Show password';
        }
    }

    function release() {
        if (repeat) { clearTimeout(repeat); repeat = null; }
        if (pressed) { pressed.classList.remove('press'); pressed = null; }
    }

    // ---- open / close --------------------------------------------------

    function restorePassword(el) {
        if (el && el.dataset.kbPw) {
            el.setAttribute('type', 'password');
            delete el.dataset.kbPw;
        }
    }

    function open(el) {
        if (!kb) build();
        if (field && field !== el) {
            field.classList.remove('hub-kb-field');
            restorePassword(field);
        }
        const fresh = field !== el;
        field = el;
        suppressNative(el);
        el.classList.add('hub-kb-field');
        if (fresh) { page = 'abc'; shift = false; caps = false; }

        const pw = el.getAttribute('type') === 'password' || !!el.dataset.kbPw;
        if (el.getAttribute('type') === 'password') el.dataset.kbPw = '1';
        showBtn.hidden = !pw;
        showBtn.classList.remove('on');
        showBtn.textContent = '👁 Show password';
        if (pw) el.setAttribute('type', 'password');
        chip.textContent = label(el);
        render();
        kb.classList.add('open');

        requestAnimationFrame(() => {
            const h = kb.offsetHeight;
            document.body.style.paddingBottom = h + 'px';
            const r = el.getBoundingClientRect();
            if (r.bottom > window.innerHeight - h - 16 || r.top < 0) {
                el.scrollIntoView({ block: 'center', behavior: 'smooth' });
            }
        });
    }

    function close() {
        release();
        if (!kb || !field) return;
        field.classList.remove('hub-kb-field');
        restorePassword(field);
        field = null;
        kb.classList.remove('open');
        document.body.style.paddingBottom = '';
    }

    // ---- wiring --------------------------------------------------------

    function scan(root) {
        (root.querySelectorAll ? root.querySelectorAll('input, textarea') : []).forEach((el) => {
            if (eligible(el)) suppressNative(el);
        });
    }

    document.addEventListener('pointerdown', (e) => {
        if (kb && kb.contains(e.target)) return;
        const el = e.target.closest && e.target.closest('input, textarea');
        if (el && eligible(el)) {
            suppressNative(el);
            open(el);
        } else if (field) {
            close();
        }
    }, true);

    // Moving focus between fields (e.g. a page's own Tab handling) while open.
    document.addEventListener('focusin', (e) => {
        if (field && e.target !== field && eligible(e.target)) open(e.target);
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && field) close();
    });

    function init() {
        scan(document);
        new MutationObserver((muts) => muts.forEach((m) => m.addedNodes.forEach((n) => {
            if (n.nodeType === 1) {
                if (n.matches('input, textarea') && eligible(n)) suppressNative(n);
                scan(n);
            }
        }))).observe(document.body, { childList: true, subtree: true });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();

    window.hubKeyboard = { open, close, isOpen: () => !!field };
})();
