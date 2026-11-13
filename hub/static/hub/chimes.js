/* Built-in pop-up chimes, synthesised with Web Audio (no files to ship).
 * The ids match bdh_sdk.alerts.CHIMES. Pages use BDHChimes.play(id) to preview;
 * alerts.js plays an alert's sound. A path on the hub plays an audio file instead. */
(function () {
    'use strict';
    let ctx = null;
    const N = {C4: 261.6, G4: 392, A4: 440, C5: 523.25, D5: 587.33, E5: 659.25, G5: 783.99,
        A5: 880, B5: 987.77, C6: 1046.5, E6: 1318.5};

    function audio() {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return null;
        ctx = ctx || new AC();
        if (ctx.state !== 'running') ctx.resume();
        return ctx;
    }

    // A bell-ish note: a fundamental plus a few partials with exponential decay.
    function bell(c, dst, t, f, dur, lvl, partials) {
        (partials || [[1, 1], [2, .35], [3, .12], [4.2, .06]]).forEach(([m, a]) => {
            const o = c.createOscillator(), g = c.createGain();
            o.type = 'sine';
            o.frequency.value = f * m;
            g.gain.setValueAtTime(0, t);
            g.gain.linearRampToValueAtTime(lvl * a, t + .008);
            g.gain.exponentialRampToValueAtTime(.0001, t + dur / (m > 1 ? m * .7 : 1));
            o.connect(g).connect(dst);
            o.start(t);
            o.stop(t + dur + .05);
        });
    }

    function tone(c, dst, t, f, dur, lvl) {
        const o = c.createOscillator(), g = c.createGain();
        o.type = 'sine';
        o.frequency.value = f;
        g.gain.setValueAtTime(0, t);
        g.gain.linearRampToValueAtTime(lvl, t + .01);
        g.gain.exponentialRampToValueAtTime(.0001, t + dur);
        o.connect(g).connect(dst);
        o.start(t);
        o.stop(t + dur + .05);
    }

    function knock(c, dst, t) {
        const n = Math.floor(c.sampleRate * .08), b = c.createBuffer(1, n, c.sampleRate), d = b.getChannelData(0);
        for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.exp(-i / (n * .12));
        const s = c.createBufferSource(), f = c.createBiquadFilter(), g = c.createGain();
        s.buffer = b;
        f.type = 'bandpass';
        f.frequency.value = 900;
        f.Q.value = 4;
        g.gain.value = 2.2;
        s.connect(f).connect(g).connect(dst);
        s.start(t);
        tone(c, dst, t, 180, .12, .5);
    }

    const pluck = [[1, 1], [5.1, .2]];
    const CHIMES = [
        ['ding-dong', 'Ding-dong', (c, d, t) => { bell(c, d, t, N.E5, 1.6, .45); bell(c, d, t + .55, N.C5, 2.2, .45); }],
        ['soft-bell', 'Soft bell', (c, d, t) => bell(c, d, t, N.A4, 3, .5, [[1, 1], [2, .4], [2.76, .2], [5.4, .06]])],
        ['rising-trio', 'Rising trio', (c, d, t) => [N.C5, N.E5, N.G5].forEach((f, i) =>
            bell(c, d, t + i * .16, f, .7, .4, [[1, 1], [4, .25], [10, .04]]))],
        ['notify', 'Notify', (c, d, t) => { tone(c, d, t, N.B5, .18, .3); tone(c, d, t + .14, N.E6, .3, .3); }],
        ['westminster', 'Westminster', (c, d, t) => [N.E5, N.C5, N.D5, N.G4].forEach((f, i) =>
            bell(c, d, t + i * .5, f, 1.6, .38))],
        ['glass-ping', 'Glass ping', (c, d, t) => bell(c, d, t, N.E6, 1.8, .3, [[1, 1], [2.4, .3], [5.95, .12]])],
        ['low-pulse', 'Low pulse', (c, d, t) => { tone(c, d, t, N.C4, .45, .5); tone(c, d, t + .5, N.C4, .6, .45); }],
        ['knock-knock', 'Knock-knock', (c, d, t) => { knock(c, d, t); knock(c, d, t + .22); }],
        ['ding-dong-ding', 'Ding-dong-ding', (c, d, t) => {
            bell(c, d, t, N.G5, 1.3, .4); bell(c, d, t + .45, N.E5, 1.3, .4); bell(c, d, t + .9, N.C5, 2.2, .4);
        }],
        ['harp-sweep', 'Harp sweep', (c, d, t) => [N.C5, N.E5, N.G5, N.C6, N.E6].forEach((f, i) =>
            bell(c, d, t + i * .07, f, 1.1, .22, [[1, 1], [2, .2]]))],
        ['kalimba', 'Kalimba', (c, d, t) => { bell(c, d, t, N.A5, .6, .45, pluck); bell(c, d, t + .2, N.E5, .9, .45, pluck); }],
        ['single-ding', 'Single ding', (c, d, t) => bell(c, d, t, N.C6, 1.2, .35)],
    ];
    const BY_ID = Object.fromEntries(CHIMES.map(([id, , fn]) => [id, fn]));
    const DEFAULT = 'ding-dong';

    // Settings → Display → Pop-up volume, passed in the screensaver's config.
    function defaultVolume() {
        try {
            const v = JSON.parse(document.getElementById('bdh-saver-cfg').textContent).chime_volume;
            if (Number.isFinite(v)) return Math.max(0, Math.min(100, v)) / 100;
        } catch (err) { /* no display app */ }
        return .7;
    }

    const isPath = s => typeof s === 'string' && s[0] === '/' && s[1] !== '/' && !s.includes('\\');

    /* Play `sound` (a chime id, null/undefined for the default, or a path on the
     * hub) at `volume` 0-1. "none" and unknown ids are silent. */
    function play(sound, volume) {
        const vol = volume == null ? defaultVolume() : Math.max(0, Math.min(1, Number(volume) || 0));
        if (sound == null || sound === '') sound = DEFAULT;
        if (vol <= 0 || sound === 'none') return false;
        if (isPath(sound)) {
            const a = new Audio(sound);
            a.volume = vol;
            a.play().catch(() => {});
            return true;
        }
        const fn = BY_ID[sound], c = fn && audio();
        if (!c) return false;
        const g = c.createGain();
        g.gain.value = vol;
        g.connect(c.destination);
        fn(c, g, c.currentTime + .05);
        return true;
    }

    window.BDHChimes = {
        play,
        DEFAULT,
        list: CHIMES.map(([id, label]) => ({id, label})),
    };
})();
