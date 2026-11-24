/* Vehicle photo gallery: main photo with thumbnails, and a fullscreen viewer with
   swipe, pinch / double-tap / wheel zoom, panning, keyboard, and swipe-down to close.
   Markup: an element with data-gallery, data-images (JSON list of URLs), data-title
   and data-label-* texts. */
(function () {
    'use strict';
    var root = document.querySelector('[data-gallery]');
    if (!root) return;
    var images = JSON.parse(root.dataset.images || '[]');
    if (!images.length) return;
    var label = function (name, fallback) { return root.dataset['label' + name] || fallback; };
    var MAX_SCALE = 4, DOUBLE_TAP_SCALE = 2.5;
    var current = 0;

    /* ---------- Main photo on the page ---------- */
    var main = document.getElementById('main-img');
    var index = document.getElementById('photo-index');
    var thumbs = Array.prototype.slice.call(document.querySelectorAll('.thumb'));
    function showInline(i) {
        current = (i + images.length) % images.length;
        if (main.getAttribute('src') !== images[current]) { main.classList.remove('is-loaded'); main.src = images[current]; }
        if (index) index.textContent = current + 1;
        thumbs.forEach(function (t, k) {
            t.classList.toggle('is-active', k === current);
            if (k === current) t.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
        });
    }
    main.addEventListener('load', function () { main.classList.add('is-loaded'); });
    thumbs.forEach(function (t) { t.addEventListener('click', function () { showInline(+t.dataset.index); }); });
    document.querySelectorAll('[data-step]').forEach(function (b) {
        b.addEventListener('click', function (e) { e.stopPropagation(); showInline(current + (+b.dataset.step)); });
    });
    var mainButton = document.getElementById('main-photo');
    (function swipeInline() {
        var x0 = null, moved = false;
        mainButton.addEventListener('touchstart', function (e) { x0 = e.touches[0].clientX; moved = false; }, { passive: true });
        mainButton.addEventListener('touchend', function (e) {
            if (x0 === null) return;
            var dx = e.changedTouches[0].clientX - x0; x0 = null;
            if (Math.abs(dx) > 40) { moved = true; showInline(current + (dx < 0 ? 1 : -1)); }
        });
        mainButton.addEventListener('click', function () { if (moved) { moved = false; return; } open(current); });
    })();

    /* ---------- Fullscreen viewer ---------- */
    var lb = document.createElement('div');
    lb.className = 'lb';
    lb.hidden = true;
    lb.setAttribute('role', 'dialog');
    lb.setAttribute('aria-modal', 'true');
    lb.setAttribute('aria-label', root.dataset.title || '');
    lb.innerHTML =
        '<div class="lb-top"><span class="lb-count"></span><span class="lb-title"></span>' +
        '<button type="button" class="lb-btn lb-close" aria-label="' + label('Close', 'Close') + '">' +
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>' +
        '<div class="lb-stage"><div class="lb-track"></div>' +
        '<button type="button" class="lb-btn lb-prev" aria-label="' + label('Previous', 'Previous') + '">←</button>' +
        '<button type="button" class="lb-btn lb-next" aria-label="' + label('Next', 'Next') + '">→</button></div>' +
        '<div class="lb-hint">' + label('Hint', '') + '</div>' +
        '<div class="lb-thumbs"></div>';
    document.body.appendChild(lb);
    var stage = lb.querySelector('.lb-stage'), track = lb.querySelector('.lb-track');
    var count = lb.querySelector('.lb-count'), strip = lb.querySelector('.lb-thumbs');
    lb.querySelector('.lb-title').textContent = root.dataset.title || '';

    var slides = images.map(function (src, i) {
        var slide = document.createElement('div');
        slide.className = 'lb-slide';
        var img = document.createElement('img');
        img.alt = (root.dataset.title || '') + ' — ' + (i + 1);
        img.draggable = false;
        img.decoding = 'async';
        img.dataset.src = src;
        slide.appendChild(img);
        track.appendChild(slide);
        var th = document.createElement('button');
        th.type = 'button';
        th.className = 'lb-thumb';
        th.setAttribute('aria-label', label('Photo', 'Photo') + ' ' + (i + 1));
        th.innerHTML = '<img src="' + src.replace(/"/g, '&quot;') + '" alt="" loading="lazy">';
        th.addEventListener('click', function () { go(i); });
        strip.appendChild(th);
        return { el: slide, img: img, thumb: th };
    });
    var hasMany = images.length > 1;
    lb.classList.toggle('lb-single', !hasMany);

    function load(i) {
        var s = slides[(i + images.length) % images.length];
        if (s && !s.img.src) s.img.src = s.img.dataset.src;
    }

    // Zoom state of the current photo.
    var z = { s: 1, x: 0, y: 0 };
    function fitted(img) {
        var W = stage.clientWidth, H = stage.clientHeight;
        var w = img.naturalWidth || W, h = img.naturalHeight || H;
        var k = Math.min(W / w, H / h);
        return { w: w * k, h: h * k, W: W, H: H };
    }
    function clamp() {
        var f = fitted(slides[current].img);
        var mx = Math.max(0, (f.w * z.s - f.W) / 2), my = Math.max(0, (f.h * z.s - f.H) / 2);
        z.x = Math.min(mx, Math.max(-mx, z.x));
        z.y = Math.min(my, Math.max(-my, z.y));
    }
    function applyZoom(animate) {
        var img = slides[current].img;
        img.style.transition = animate ? 'transform .25s ease' : 'none';
        img.style.transform = 'translate(' + z.x + 'px,' + z.y + 'px) scale(' + z.s + ')';
        lb.classList.toggle('is-zoomed', z.s > 1.01);
    }
    function resetZoom(animate) { z = { s: 1, x: 0, y: 0 }; applyZoom(animate); }
    function zoomAt(scale, px, py, animate) {
        // Keep the image point under (px, py) — relative to the stage centre — in place.
        var s1 = Math.min(MAX_SCALE, Math.max(1, scale));
        z.x = px - (px - z.x) * s1 / z.s;
        z.y = py - (py - z.y) * s1 / z.s;
        z.s = s1;
        if (s1 === 1) { z.x = 0; z.y = 0; }
        clamp(); applyZoom(animate);
    }
    function centred(e) {
        var r = stage.getBoundingClientRect();
        return { x: e.clientX - r.left - r.width / 2, y: e.clientY - r.top - r.height / 2 };
    }

    function position(offset, animate) {
        track.style.transition = animate ? 'transform .35s cubic-bezier(.2,.8,.2,1)' : 'none';
        track.style.transform = 'translate3d(calc(' + (-current * 100) + '% + ' + (offset || 0) + 'px),0,0)';
    }
    function go(i, animate) {
        if (z.s > 1) resetZoom(false);
        current = (i + images.length) % images.length;
        load(current); load(current + 1); load(current - 1);
        position(0, animate !== false);
        count.textContent = (current + 1) + ' / ' + images.length;
        slides.forEach(function (s, k) {
            s.thumb.classList.toggle('is-active', k === current);
            s.el.setAttribute('aria-hidden', k === current ? 'false' : 'true');
        });
        slides[current].thumb.scrollIntoView({ block: 'nearest', inline: 'center' });
        showInline(current);
    }
    lb.querySelector('.lb-prev').addEventListener('click', function () { go(current - 1); });
    lb.querySelector('.lb-next').addEventListener('click', function () { go(current + 1); });

    /* Open / close; the phone's Back button closes the viewer. */
    var lastFocus, pushed = false;
    function open(i) {
        lastFocus = document.activeElement;
        lb.hidden = false;
        document.documentElement.style.overflow = 'hidden';
        go(i, false);
        lb.style.opacity = '';
        lb.querySelector('.lb-close').focus({ preventScroll: true });
        try { history.pushState({ lightbox: true }, ''); pushed = true; } catch (e) { pushed = false; }
    }
    function close(fromHistory) {
        if (lb.hidden) return;
        lb.hidden = true;
        document.documentElement.style.overflow = '';
        resetZoom(false);
        if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true });
        if (pushed && !fromHistory) { pushed = false; history.back(); }
        pushed = false;
    }
    window.addEventListener('popstate', function () { if (!lb.hidden) close(true); });
    lb.querySelector('.lb-close').addEventListener('click', function () { close(); });
    document.addEventListener('keydown', function (e) {
        if (lb.hidden) return;
        if (e.key === 'Escape') { e.preventDefault(); close(); }
        else if (e.key === 'ArrowLeft') go(current - 1);
        else if (e.key === 'ArrowRight') go(current + 1);
        else if (e.key === '+' || e.key === '=') zoomAt(z.s * 1.5, 0, 0, true);
        else if (e.key === '-') zoomAt(z.s / 1.5, 0, 0, true);
        else if (e.key === 'Tab') { // keep focus inside the viewer
            var f = lb.querySelectorAll('button'); var first = f[0], last = f[f.length - 1];
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
    });
    window.addEventListener('resize', function () { if (!lb.hidden) { position(0, false); clamp(); applyZoom(false); } });

    /* Wheel zoom (desktop) and double-click / double-tap zoom. */
    stage.addEventListener('wheel', function (e) {
        e.preventDefault();
        var p = centred(e);
        zoomAt(z.s * Math.exp(-e.deltaY * 0.0022), p.x, p.y, false);
    }, { passive: false });
    var lastTap = 0;
    function toggleZoom(e) {
        var p = centred(e);
        if (z.s > 1.01) resetZoom(true); else zoomAt(DOUBLE_TAP_SCALE, p.x, p.y, true);
    }

    /* Pointer gestures: swipe between photos, pan when zoomed, pinch to zoom,
       swipe down to close. */
    var pointers = {}, gesture = null;
    function list() { return Object.keys(pointers).map(function (k) { return pointers[k]; }); }
    stage.addEventListener('pointerdown', function (e) {
        if (e.target.closest('.lb-btn')) return;
        stage.setPointerCapture(e.pointerId);
        pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
        var pts = list();
        if (pts.length === 2) {
            var m = centred({ clientX: (pts[0].x + pts[1].x) / 2, clientY: (pts[0].y + pts[1].y) / 2 });
            gesture = { type: 'pinch', d0: Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y),
                        s0: z.s, x0: z.x, y0: z.y, m0: m };
        } else if (pts.length === 1) {
            gesture = { type: 'drag', sx: e.clientX, sy: e.clientY, x0: z.x, y0: z.y, t: Date.now(), axis: null };
        }
    });
    stage.addEventListener('pointermove', function (e) {
        if (!pointers[e.pointerId] || !gesture) return;
        pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
        var pts = list();
        if (gesture.type === 'pinch' && pts.length === 2) {
            var d = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
            var m = centred({ clientX: (pts[0].x + pts[1].x) / 2, clientY: (pts[0].y + pts[1].y) / 2 });
            var s1 = Math.min(MAX_SCALE, Math.max(1, gesture.s0 * d / gesture.d0));
            z.s = s1;
            z.x = m.x - (gesture.m0.x - gesture.x0) * s1 / gesture.s0;
            z.y = m.y - (gesture.m0.y - gesture.y0) * s1 / gesture.s0;
            clamp(); applyZoom(false);
        } else if (gesture.type === 'drag') {
            var dx = e.clientX - gesture.sx, dy = e.clientY - gesture.sy;
            if (z.s > 1.01) { z.x = gesture.x0 + dx; z.y = gesture.y0 + dy; clamp(); applyZoom(false); return; }
            if (!gesture.axis && Math.hypot(dx, dy) > 8) gesture.axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
            if (gesture.axis === 'x' && hasMany) position(dx, false);
            if (gesture.axis === 'y' && dy > 0) {
                track.style.transition = 'none';
                track.style.transform = 'translate3d(' + (-current * 100) + '%,' + dy + 'px,0)';
                lb.style.opacity = String(Math.max(0.35, 1 - dy / 500));
            }
        }
    });
    function end(e) {
        if (!pointers[e.pointerId]) return;
        delete pointers[e.pointerId];
        if (!gesture) return;
        if (gesture.type === 'pinch') {
            if (list().length === 0) { if (z.s < 1.05) resetZoom(true); gesture = null; }
            else gesture = null;  // one finger left: wait for it to lift
            return;
        }
        var dx = e.clientX - gesture.sx, dy = e.clientY - gesture.sy, dt = Date.now() - gesture.t;
        var tap = Math.hypot(dx, dy) < 8 && dt < 300;
        if (gesture.axis === 'x' && z.s <= 1.01) {
            var fast = Math.abs(dx) / Math.max(dt, 1) > 0.5;
            if (hasMany && (Math.abs(dx) > stage.clientWidth * 0.18 || (fast && Math.abs(dx) > 30))) go(current + (dx < 0 ? 1 : -1));
            else position(0, true);
        } else if (gesture.axis === 'y' && z.s <= 1.01) {
            if (dy > 120) { lb.style.opacity = ''; close(); }
            else { lb.style.opacity = ''; position(0, true); }
        } else if (tap) {
            var now = Date.now();
            if (now - lastTap < 300) { toggleZoom(e); lastTap = 0; } else lastTap = now;
        }
        gesture = null;
    }
    stage.addEventListener('pointerup', end);
    stage.addEventListener('pointercancel', end);
})();
