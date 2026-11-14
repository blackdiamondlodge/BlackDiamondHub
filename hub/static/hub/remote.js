/* Remote control for development (hub/remote.py). Loaded only while
 * HUB_REMOTE_TOKEN is set on the hub. Each page connects to ws/hub/remote/
 * and runs the commands the hub forwards:
 *
 *   state                         page, size, fullscreen element, videos
 *   query   {selector, text, limit}            matching elements and where they are
 *   tap     {x, y} | {selector, index, text}, fingers, hold_ms
 *   swipe   {x1, y1, x2, y2, ms, fingers}
 *   key     {key}                 keydown/keyup on the focused element
 *   type    {text}                set the focused input's value
 *   scroll  {selector, dx, dy}
 *   measure {seconds}             frame rate, long tasks, per-video decode/drop/present rates
 *   logs    {n, clear}            recent console output and page errors
 *   navigate {url} | reload | back
 *   eval    {code}                async function body; its return value comes back
 *
 * Synthetic taps carry no user activation, so the browser refuses
 * requestFullscreen. While this script is loaded a refused request falls back
 * to a stand-in fullscreen: the element is pinned over the page, gets the
 * page's own :fullscreen styles (copied to .hub-remote-fs), and
 * document.fullscreenElement / exitFullscreen / fullscreenchange behave as
 * they would for a real one. Real taps still get real fullscreen. */
(function () {
    'use strict';
    let ws = null, backoff = 1000;

    // ---- console capture -------------------------------------------------
    const LOG_MAX = 300;
    const logs = [];
    function note(level, args) {
        let text;
        try {
            text = Array.from(args).map(a => (typeof a === 'string' ? a : JSON.stringify(plain(a, 2)))).join(' ');
        } catch (e) { text = String(args[0]); }
        logs.push({ t: Math.round(performance.now()), level, text: text.slice(0, 2000) });
        if (logs.length > LOG_MAX) logs.shift();
    }
    ['log', 'info', 'warn', 'error', 'debug'].forEach(level => {
        const orig = console[level];
        console[level] = function () { note(level, arguments); return orig.apply(this, arguments); };
    });
    window.addEventListener('error', e => note('pageerror', [`${e.message} @ ${e.filename}:${e.lineno}`]));
    window.addEventListener('unhandledrejection', e => note('rejection', [String(e.reason && (e.reason.stack || e.reason))]));

    // ---- helpers ---------------------------------------------------------
    function describe(el) {
        if (!el || !el.getBoundingClientRect) return null;
        const r = el.getBoundingClientRect();
        return {
            tag: el.tagName.toLowerCase(), id: el.id || undefined,
            cls: (typeof el.className === 'string' && el.className) || undefined,
            text: (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').trim().replace(/\s+/g, ' ').slice(0, 80) || undefined,
            rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
        };
    }

    function plain(value, depth, seen) {
        seen = seen || new WeakSet();
        if (value === null || value === undefined) return value === undefined ? null : value;
        const t = typeof value;
        if (t === 'number' || t === 'string' || t === 'boolean') return value;
        if (t === 'bigint') return String(value);
        if (t === 'function') return `[function ${value.name || ''}]`;
        if (value instanceof Element) return describe(value);
        if (value instanceof Error) return { error: value.message, stack: value.stack };
        if (seen.has(value)) return '[circular]';
        seen.add(value);
        if (depth <= 0) return Array.isArray(value) ? `[array ${value.length}]` : '[object]';
        if (value instanceof Map || (typeof value.get === 'function' && typeof value.entries === 'function' && !Array.isArray(value))) {
            value = Object.fromEntries(Array.from(value.entries()).slice(0, 200));
        }
        if (value instanceof Set || value instanceof NodeList || value instanceof HTMLCollection) value = Array.from(value);
        if (Array.isArray(value)) return value.slice(0, 200).map(v => plain(v, depth - 1, seen));
        const out = {};
        let keys = Object.keys(value);
        if (!keys.length && typeof value.toJSON === 'function') return plain(value.toJSON(), depth, seen);
        if (!keys.length) for (const k in value) keys.push(k);  // DOMRect, stats objects
        for (const k of keys.slice(0, 200)) {
            try { out[k] = plain(value[k], depth - 1, seen); } catch (e) { out[k] = '[unreadable]'; }
        }
        return out;
    }

    function visible(el) {
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) return false;
        const s = getComputedStyle(el);
        return s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity !== 0;
    }

    function find(args) {
        const scope = document.fullscreenElement || document;
        let els = Array.from(scope.querySelectorAll(args.selector || '*'));
        if (scope !== document && !els.length) els = Array.from(document.querySelectorAll(args.selector || '*'));
        if (args.text) {
            const want = String(args.text).toLowerCase();
            els = els.filter(el => (el.innerText || el.value || el.getAttribute('aria-label') || '').toLowerCase().includes(want));
            // Innermost matches only: a card's text also matches every ancestor.
            els = els.filter(el => !els.some(o => o !== el && el.contains(o)));
        }
        return els.filter(visible);
    }

    function point(args) {
        if (args.x !== undefined) return { x: +args.x, y: +args.y };
        const el = find(args)[args.index || 0];
        if (!el) throw new Error(`nothing matches ${JSON.stringify(args)}`);
        let r = el.getBoundingClientRect();
        const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
        if (cx < 0 || cx >= innerWidth || cy < 0 || cy >= innerHeight) {
            el.scrollIntoView({ block: 'center', inline: 'center' });
            r = el.getBoundingClientRect();
        }
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    }

    const sleep = ms => new Promise(res => setTimeout(res, ms));
    let remoteGesture = 0;

    function touches(target, x, y, fingers) {
        const list = [];
        for (let i = 0; i < fingers; i++) {
            list.push(new Touch({ identifier: Date.now() + i, target, clientX: x + i * 30, clientY: y,
                                  pageX: x + i * 30 + scrollX, pageY: y + scrollY, radiusX: 10, radiusY: 10, force: 1 }));
        }
        return list;
    }

    function fire(target, type, x, y, fingers, active) {
        const base = { bubbles: true, cancelable: true, composed: true, clientX: x, clientY: y, view: window };
        if (type.startsWith('touch')) {
            const t = touches(target, x, y, fingers);
            return target.dispatchEvent(new TouchEvent(type, { ...base, touches: active ? t : [], targetTouches: active ? t : [], changedTouches: t }));
        }
        if (type.startsWith('pointer')) {
            return target.dispatchEvent(new PointerEvent(type, { ...base, pointerId: 1, pointerType: 'touch', isPrimary: true,
                                                                 buttons: active ? 1 : 0, pressure: active ? 0.5 : 0 }));
        }
        return target.dispatchEvent(new MouseEvent(type, { ...base, buttons: active ? 1 : 0 }));
    }

    async function tap(args) {
        const { x, y } = point(args);
        const fingers = Math.max(1, Math.min(5, args.fingers || 1));
        const target = document.elementFromPoint(x, y);
        if (!target) throw new Error(`nothing at ${Math.round(x)},${Math.round(y)}`);
        remoteGesture++;
        try {
            fire(target, 'pointerdown', x, y, fingers, true);
            const startOk = fire(target, 'touchstart', x, y, fingers, true);
            await sleep(args.hold_ms || 60);
            fire(target, 'pointerup', x, y, fingers, false);
            const endOk = fire(target, 'touchend', x, y, fingers, false);
            if (fingers === 1 && startOk && endOk) {
                fire(target, 'mousedown', x, y, 1, true);
                fire(target, 'mouseup', x, y, 1, false);
                // Same-call click, so code that requests fullscreen sees the remote gesture.
                fire(target, 'click', x, y, 1, false);
            }
        } finally { remoteGesture--; }
        return { at: [Math.round(x), Math.round(y)], target: describe(target) };
    }

    async function swipe(args) {
        const fingers = Math.max(1, Math.min(5, args.fingers || 1));
        const ms = args.ms || 300, steps = Math.max(2, args.steps || 12);
        const target = document.elementFromPoint(args.x1, args.y1);
        if (!target) throw new Error('nothing at the start point');
        fire(target, 'pointerdown', args.x1, args.y1, fingers, true);
        fire(target, 'touchstart', args.x1, args.y1, fingers, true);
        let x = args.x1, y = args.y1;
        for (let i = 1; i <= steps; i++) {
            await sleep(ms / steps);
            x = args.x1 + (args.x2 - args.x1) * i / steps;
            y = args.y1 + (args.y2 - args.y1) * i / steps;
            fire(target, 'pointermove', x, y, fingers, true);
            fire(target, 'touchmove', x, y, fingers, true);
        }
        fire(target, 'pointerup', x, y, fingers, false);
        fire(target, 'touchend', x, y, fingers, false);
        return { target: describe(target) };
    }

    // ---- stand-in fullscreen ---------------------------------------------
    const fsStack = [];
    const fsTop = () => fsStack[fsStack.length - 1] || null;
    const realRequest = Element.prototype.requestFullscreen;
    const realExit = Document.prototype.exitFullscreen;
    const realElement = Object.getOwnPropertyDescriptor(Document.prototype, 'fullscreenElement');
    let fsStyled = false;

    function copyFullscreenStyles() {
        if (fsStyled) return;
        fsStyled = true;
        const sheet = document.head.appendChild(document.createElement('style'));
        sheet.textContent = '.hub-remote-fs{position:fixed!important;inset:0!important;width:100vw!important;' +
            'height:100vh!important;max-width:none!important;max-height:none!important;margin:0!important;' +
            'z-index:2147483646!important;border-radius:0!important;background:#000;}';
        const extra = [];
        const walk = rules => {
            for (const rule of rules) {
                if (rule.cssRules && !rule.selectorText) {
                    if (rule.media) {
                        const inner = [];
                        for (const r of rule.cssRules) if (r.selectorText && r.selectorText.includes(':fullscreen')) {
                            inner.push(r.cssText.split(':fullscreen').join('.hub-remote-fs'));
                        }
                        if (inner.length) extra.push(`@media ${rule.media.mediaText}{${inner.join('')}}`);
                    }
                    continue;
                }
                if (rule.selectorText && rule.selectorText.includes(':fullscreen')) {
                    extra.push(rule.cssText.split(':fullscreen').join('.hub-remote-fs'));
                }
            }
        };
        for (const s of Array.from(document.styleSheets)) {
            try { walk(s.cssRules); } catch (e) { /* cross-origin sheet */ }
        }
        for (const text of extra) {
            try { sheet.sheet.insertRule(text, sheet.sheet.cssRules.length); } catch (e) { /* not valid on its own */ }
        }
    }

    function fsChanged(el) {
        el.dispatchEvent(new Event('fullscreenchange', { bubbles: true, composed: true }));
    }

    Object.defineProperty(Document.prototype, 'fullscreenElement', {
        configurable: true,
        get() { return realElement.get.call(this) || (this === document ? fsTop() : null); },
    });

    Element.prototype.requestFullscreen = function (options) {
        const el = this, gesture = remoteGesture > 0;
        return realRequest.call(el, options).catch(err => {
            if (!gesture && !fsStack.length) throw err;
            copyFullscreenStyles();
            const prev = fsTop();
            if (prev === el) return;
            const i = fsStack.indexOf(el);
            if (i >= 0) fsStack.splice(i, 1);
            fsStack.push(el);
            if (prev) prev.classList.remove('hub-remote-fs');
            el.classList.add('hub-remote-fs');
            fsChanged(el);
        });
    };

    Document.prototype.exitFullscreen = function () {
        if (realElement.get.call(this) || !fsStack.length) return realExit.call(this);
        const el = fsStack.pop();
        el.classList.remove('hub-remote-fs');
        const next = fsTop();
        if (next) next.classList.add('hub-remote-fs');
        fsChanged(el);
        return Promise.resolve();
    };

    // ---- state and measurement -------------------------------------------
    function videoInfo(v) {
        const q = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : {};
        return {
            ...describe(v), src: (v.currentSrc || (v.srcObject ? '[stream]' : '')).slice(-120),
            size: [v.videoWidth, v.videoHeight], paused: v.paused, ended: v.ended, readyState: v.readyState,
            time: +v.currentTime.toFixed(2), duration: isFinite(v.duration) ? +v.duration.toFixed(2) : null,
            buffered: v.buffered.length ? +(v.buffered.end(v.buffered.length - 1) - v.currentTime).toFixed(1) : 0,
            decoded: q.totalVideoFrames, dropped: q.droppedVideoFrames,
            onscreen: visible(v),
        };
    }

    function state() {
        const fs = document.fullscreenElement;
        return {
            url: location.href, title: document.title, size: [innerWidth, innerHeight], dpr: devicePixelRatio,
            visibility: document.visibilityState, fullscreen: describe(fs),
            fullscreen_kind: fs ? (realElement.get.call(document) ? 'real' : 'stand-in') : null,
            active: describe(document.activeElement),
            videos: Array.from(document.querySelectorAll('video')).map(videoInfo),
            memory_mb: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null,
            uptime_s: Math.round(performance.now() / 1000),
        };
    }

    async function measure(args) {
        const seconds = Math.max(1, Math.min(60, args.seconds || 5));
        const videos = Array.from(document.querySelectorAll('video')).filter(v => !v.paused && v.readyState > 2);
        const before = videos.map(v => (v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : {}));
        const presented = videos.map(() => 0);
        let live = true;
        videos.forEach((v, i) => {
            if (!v.requestVideoFrameCallback) return;
            const cb = () => { presented[i]++; if (live) v.requestVideoFrameCallback(cb); };
            v.requestVideoFrameCallback(cb);
        });
        let frames = 0, last = performance.now(), worst = 0, slow = 0;
        const raf = now => {
            frames++;
            const gap = now - last;
            last = now;
            worst = Math.max(worst, gap);
            if (gap > 50) slow++;
            if (live) requestAnimationFrame(raf);
        };
        requestAnimationFrame(raf);
        const tasks = [];
        let observer = null;
        try {
            observer = new PerformanceObserver(list => tasks.push(...list.getEntries().map(e => e.duration)));
            observer.observe({ type: 'longtask' });
        } catch (e) { /* unsupported */ }
        await sleep(seconds * 1000);
        live = false;
        if (observer) observer.disconnect();
        const per = n => +(n / seconds).toFixed(1);
        return {
            seconds, raf_fps: per(frames), worst_frame_ms: Math.round(worst), frames_over_50ms: slow,
            long_tasks: tasks.length, long_task_ms: Math.round(tasks.reduce((a, b) => a + b, 0)),
            videos: videos.map((v, i) => {
                const q = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : {};
                return {
                    ...describe(v), size: [v.videoWidth, v.videoHeight], src: (v.currentSrc || '[stream]').slice(-80),
                    decoded_fps: per((q.totalVideoFrames || 0) - (before[i].totalVideoFrames || 0)),
                    dropped_fps: per((q.droppedVideoFrames || 0) - (before[i].droppedVideoFrames || 0)),
                    presented_fps: per(presented[i]),
                };
            }),
        };
    }

    // ---- commands --------------------------------------------------------
    const later = fn => { setTimeout(fn, 100); return { ok: true }; };
    const AsyncFunction = (async () => {}).constructor;

    const commands = {
        state,
        query: args => find(args).slice(0, args.limit || 50).map(describe),
        tap, swipe, measure,
        key(args) {
            const target = document.activeElement || document.body;
            const init = { key: args.key, code: args.code || args.key, bubbles: true, cancelable: true };
            target.dispatchEvent(new KeyboardEvent('keydown', init));
            target.dispatchEvent(new KeyboardEvent('keyup', init));
            return describe(target);
        },
        type(args) {
            const el = document.activeElement;
            if (!el || !('value' in el)) throw new Error('no focused input');
            el.value = args.append ? el.value + args.text : args.text;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return describe(el);
        },
        scroll(args) {
            const el = args.selector ? find(args)[args.index || 0] : document.scrollingElement;
            if (!el) throw new Error('nothing to scroll');
            el.scrollBy(args.dx || 0, args.dy || 0);
            return { top: el.scrollTop, left: el.scrollLeft };
        },
        logs(args) {
            const out = logs.slice(-(args.n || 100));
            if (args.clear) logs.length = 0;
            return out;
        },
        navigate: args => later(() => { location.href = args.url; }),
        reload: () => later(() => location.reload()),
        back: () => later(() => history.back()),
        eval: args => new AsyncFunction(args.code)(),
    };

    async function run(msg) {
        let reply;
        try {
            const fn = commands[msg.cmd];
            if (!fn) throw new Error(`unknown command ${msg.cmd}; try ${Object.keys(commands).join(', ')}`);
            reply = { ok: true, value: plain(await fn(msg.args || {}), msg.args && msg.args.depth || 6) };
        } catch (err) {
            reply = { ok: false, error: String(err && (err.stack || err)) };
        }
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'result', id: msg.id, ...reply }));
    }

    // ---- connection ------------------------------------------------------
    function hello() {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        ws.send(JSON.stringify({ type: 'hello', path: location.pathname + location.search, title: document.title,
                                 size: [innerWidth, innerHeight], ua: navigator.userAgent }));
    }

    function connect() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(proto + '//' + location.host + '/ws/hub/remote/');
        ws.onopen = () => { backoff = 1000; hello(); };
        ws.onmessage = e => {
            let msg;
            try { msg = JSON.parse(e.data); } catch (err) { return; }
            if (msg && msg.type === 'cmd') run(msg);
        };
        ws.onclose = () => {
            ws = null;
            setTimeout(connect, backoff);
            backoff = Math.min(backoff * 2, 30000);
        };
    }

    let resizeTimer = null;
    window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(hello, 500); });
    window.BDHRemote = { commands, state };
    connect();
})();
