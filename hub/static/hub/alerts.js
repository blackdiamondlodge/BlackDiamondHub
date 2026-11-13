/* Pop-up alerts pushed by apps through bdh_sdk.alerts (see hub/alerts.py).
 * One alert at a time: the newest replaces the current one, and a repeat of the
 * same key just restarts its countdown (unless "Keep open" was tapped). A new
 * alert plays its sound (chimes.js) unless it's the night window.
 * Only the hub's own display listens. */
(function () {
    'use strict';
    const isDisplay = () => window.innerWidth >= 1280;
    let ws = null, backoff = 1000, retry = null, resizeTimer = null;
    const KEEP_MAX_S = 600;
    let root = null, current = null, closeTimer = null, kept = false;

    function el(tag, cls) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        return e;
    }

    function build() {
        root = el('div', 'hub-alert');
        root.setAttribute('role', 'dialog');
        root.setAttribute('aria-modal', 'true');
        root.innerHTML =
            '<div class="hub-alert-card">' +
            '<div class="hub-alert-head"><div class="hub-alert-text">' +
            '<div class="hub-alert-title"></div><div class="hub-alert-body"></div></div>' +
            '<button type="button" class="hub-alert-keep" aria-pressed="false">' +
            '<i class="fas fa-thumbtack"></i><span>Keep open</span></button>' +
            '<button type="button" class="hub-alert-close" aria-label="Close">' +
            '<i class="fas fa-times"></i></button></div>' +
            '<div class="hub-alert-frame"></div>' +
            '<div class="hub-alert-bar"><span></span></div></div>';
        root.addEventListener('click', e => {
            if (e.target.closest('.hub-alert-keep')) keepOpen();
            else if (e.target === root || e.target.closest('.hub-alert-close')) close();
        });
        document.body.appendChild(root);
    }

    function setKept(on) {
        kept = on;
        root.classList.toggle('kept', on);
        const btn = root.querySelector('.hub-alert-keep');
        btn.setAttribute('aria-pressed', String(on));
        btn.querySelector('span').textContent = on ? 'Kept open' : 'Keep open';
    }

    /* Stop the countdown; the alert stays until closed, up to a safety cap so a
     * forgotten live feed doesn't stream (and hold off the screensaver) forever. */
    function keepOpen() {
        if (!current || kept) return;
        setKept(true);
        clearTimeout(closeTimer);
        closeTimer = setTimeout(close, KEEP_MAX_S * 1000);
    }

    function startTimer(ttl) {
        clearTimeout(closeTimer);
        closeTimer = setTimeout(close, ttl * 1000);
        const bar = root.querySelector('.hub-alert-bar span');
        bar.style.transition = 'none';
        bar.style.transform = 'scaleX(1)';
        void bar.offsetWidth;
        bar.style.transition = 'transform ' + ttl + 's linear';
        bar.style.transform = 'scaleX(0)';
    }

    function show(alert) {
        if (!root) build();
        const saver = window.BDHSaver;
        if (saver) {
            if (alert.wake !== false && saver.wake) saver.wake();
            if (saver.pause) saver.pause();
        }
        const same = current && current.key === alert.key && current.embed_url === alert.embed_url;
        current = alert;
        // A new alert chimes; repeats (another ring) and the night window stay quiet.
        if (!same && window.BDHChimes && !(saver && saver.isNight && saver.isNight())) {
            window.BDHChimes.play(alert.sound);
        }
        if (!same) {
            const frame = root.querySelector('.hub-alert-frame');
            frame.textContent = '';
            const iframe = el('iframe');
            iframe.setAttribute('allow', 'autoplay; fullscreen');
            iframe.setAttribute('title', alert.title || 'Alert');
            iframe.src = alert.embed_url;
            frame.appendChild(iframe);
        }
        root.querySelector('.hub-alert-title').textContent = alert.title || '';
        const body = root.querySelector('.hub-alert-body');
        body.textContent = alert.body || '';
        body.hidden = !alert.body;
        root.classList.add('on');
        if (!same) setKept(false);
        // A repeat of a kept alert (e.g. another ring) leaves it kept open.
        if (!kept) startTimer(Math.max(1, Math.min(600, alert.ttl || 60)));
    }

    function close() {
        if (!root || !current) return;
        clearTimeout(closeTimer);
        current = null;
        setKept(false);
        root.classList.remove('on');
        // Drop the iframe so live video stops streaming.
        root.querySelector('.hub-alert-frame').textContent = '';
        const saver = window.BDHSaver;
        if (saver && saver.resume) saver.resume();
    }

    function connect() {
        clearTimeout(retry);
        if (ws || !isDisplay()) return;
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(proto + '//' + location.host + '/ws/hub/alerts/');
        ws.onopen = () => { backoff = 1000; };
        ws.onmessage = e => {
            let msg;
            try { msg = JSON.parse(e.data); } catch (err) { return; }
            if (msg && msg.type === 'alert' && typeof msg.embed_url === 'string'
                && msg.embed_url[0] === '/' && msg.embed_url[1] !== '/') show(msg);
        };
        ws.onclose = () => {
            ws = null;
            if (!isDisplay()) return;
            retry = setTimeout(connect, backoff);
            backoff = Math.min(backoff * 2, 30000);
        };
    }

    function disconnect() {
        clearTimeout(retry);
        if (ws) { ws.onclose = null; ws.close(); ws = null; }
        close();
    }

    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => (isDisplay() ? connect() : disconnect()), 500);
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
    window.BDHAlerts = {show, close, keepOpen};
    connect();
})();
