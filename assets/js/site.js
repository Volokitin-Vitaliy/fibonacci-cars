/* Site-wide behaviour: search, favorites, header, reveal animations. */
/* Search with instant results: header window and the catalog's search field. */
(function () {
    var overlay = document.getElementById('search-overlay');
    var esc = function (t) { return String(t).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); };
    var texts = (overlay || document.body).dataset;
    var T = { all: texts.tAll || 'Show all results', none: texts.tNone || 'Nothing found.' };
    function highlight(text, words) {
        var out = esc(text);
        words.forEach(function (w) { if (w.length > 1) out = out.replace(new RegExp('(' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig'), '<mark>$1</mark>'); });
        return out;
    }
    function setup(root) {
        var input = root.querySelector('[data-search-input]'), box = root.querySelector('[data-search-results]');
        var hint = root.querySelector('[data-search-hint]'), url = root.dataset.suggestUrl;
        var timer, controller, active = -1;
        function items() { return Array.prototype.slice.call(box.querySelectorAll('.search-item, .search-all')); }
        function setActive(i) {
            var list = items(); list.forEach(function (el) { el.classList.remove('is-active'); });
            active = list.length ? (i + list.length) % list.length : -1;
            if (active >= 0) { list[active].classList.add('is-active'); list[active].scrollIntoView({ block: 'nearest' }); }
        }
        function render(data, q) {
            var words = q.toLowerCase().split(/\s+/);
            if (!data.results.length) { box.innerHTML = '<div class="search-empty">' + T.none + '</div>'; return; }
            box.innerHTML = data.results.map(function (r) {
                var img = r.image ? '<img src="' + esc(r.image) + '" alt="" loading="lazy">' : '<span class="search-thumb"></span>';
                return '<a class="search-item" href="' + esc(r.url) + '">' + img + '<span class="min-w-0 flex-1"><span class="block text-[0.68rem] uppercase tracking-[0.2em] text-neutral-500">' + highlight(r.make, words) + '</span><span class="block truncate font-medium">' + highlight(r.title, words) + '</span><span class="block text-xs text-neutral-400 mt-0.5">' + [r.year, r.price].filter(Boolean).map(esc).join(' · ') + '</span></span></a>';
            }).join('') + '<a class="search-all" href="' + esc(data.all_url) + '"><span>' + T.all + '</span><span aria-hidden="true">→</span></a>';
        }
        function run() {
            var q = input.value.trim(); active = -1;
            if (q.length < 2) { box.innerHTML = ''; if (hint) box.appendChild(hint); if (!hint) box.hidden = true; return; }
            if (controller) controller.abort();
            controller = window.AbortController ? new AbortController() : null;
            fetch(url + '?q=' + encodeURIComponent(q), controller ? { signal: controller.signal } : {})
                .then(function (r) { return r.json(); })
                .then(function (data) { if (input.value.trim() === q) { box.hidden = false; render(data, q); } })
                .catch(function () {});
        }
        input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(run, 160); });
        input.addEventListener('focus', function () { if (input.value.trim().length >= 2 && !box.children.length) run(); else if (box.children.length) box.hidden = false; });
        input.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowDown') { e.preventDefault(); setActive(active + 1); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(active - 1); }
            else if (e.key === 'Enter' && active >= 0) { e.preventDefault(); items()[active].click(); }
        });
        if (root.classList.contains('search-inline')) {
            document.addEventListener('click', function (e) { if (!root.contains(e.target)) box.hidden = true; });
            input.addEventListener('keydown', function (e) { if (e.key === 'Escape') box.hidden = true; });
        }
        root.searchInput = input;
    }
    document.querySelectorAll('[data-search]').forEach(setup);
    if (!overlay) return;
    var lastFocus;
    function open() {
        lastFocus = document.activeElement; overlay.hidden = false; document.documentElement.style.overflow = 'hidden';
        var input = overlay.querySelector('[data-search-input]'); input.focus(); input.select();
    }
    function close() { overlay.hidden = true; document.documentElement.style.overflow = ''; if (lastFocus && lastFocus.focus) lastFocus.focus(); }
    document.querySelectorAll('[data-search-open]').forEach(function (b) { b.addEventListener('click', open); });
    overlay.querySelectorAll('[data-search-close]').forEach(function (b) { b.addEventListener('click', close); });
    document.addEventListener('keydown', function (e) {
        var typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || '')) || e.target.isContentEditable;
        if (!overlay.hidden && e.key === 'Escape') { e.preventDefault(); close(); }
        else if (overlay.hidden && ((e.key === '/' && !typing) || ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k'))) { e.preventDefault(); open(); }
    });
})();

/* Favorites without reloading the page; works for guests too. */
document.addEventListener('submit', function (e) {
    var form = e.target.closest('[data-favorite-form]');
    if (!form || !window.fetch) return;
    e.preventDefault();
    var button = form.querySelector('button');
    fetch(form.action, {method: 'POST', body: new FormData(form), headers: {'X-Requested-With': 'fetch'}, credentials: 'same-origin'})
        .then(function (r) { if (!r.ok) throw r; return r.json(); })
        .then(function (data) {
            document.querySelectorAll('form[action="' + form.getAttribute('action') + '"] button').forEach(function (b) {
                b.dataset.fav = data.favorite ? '1' : '0';
                b.setAttribute('aria-pressed', data.favorite);
                b.title = data.favorite ? b.dataset.titleOn : b.dataset.titleOff;
                b.classList.toggle('text-red-400', data.favorite);
                b.classList.toggle('text-white', !data.favorite);
                var icon = b.querySelector('[data-fav-icon]'); if (icon) icon.textContent = data.favorite ? '♥' : '♡';
                var label = b.querySelector('[data-fav-label]'); if (label) label.textContent = data.favorite ? label.dataset.on : label.dataset.off;
            });
            document.querySelectorAll('[data-fav-count]').forEach(function (el) {
                el.textContent = data.count;
                if (el.hasAttribute('data-fav-badge')) el.classList.toggle('hidden', !data.count);
            });
            button.animate && button.animate([{transform: 'scale(1)'}, {transform: 'scale(1.25)'}, {transform: 'scale(1)'}], {duration: 250});
        })
        .catch(function () { form.submit(); });
});

(function () {
    var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    // Header gets more solid once the page is scrolled.
    var header = document.querySelector('.site-header');
    var onScroll = function () { header.classList.toggle('is-scrolled', window.scrollY > 8); };
    // The first state (e.g. a page reloaded halfway down) is set without the fade.
    header.classList.add('no-motion'); onScroll(); header.getBoundingClientRect();
    requestAnimationFrame(function () { header.classList.remove('no-motion'); });
    window.addEventListener('scroll', onScroll, {passive: true});

    // Thin loading bar while the next page loads.
    var bar = document.getElementById('page-progress');
    document.addEventListener('click', function (e) {
        var a = e.target.closest('a[href]');
        if (!a || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || a.target === '_blank') return;
        var url = new URL(a.href, location.href);
        if (url.origin !== location.origin || url.hash && url.pathname === location.pathname) return;
        bar.classList.add('is-active');
    });
    document.addEventListener('submit', function (e) { if (!e.target.matches('[data-favorite-form]')) bar.classList.add('is-active'); });
    window.addEventListener('pageshow', function () { bar.classList.remove('is-active'); });

    // Reveal blocks and count numbers up when they scroll into view.
    var countUp = function (el) {
        var target = parseFloat(el.dataset.count), suffix = el.dataset.suffix || '', start = null;
        if (reduce || !target) { el.textContent = (el.dataset.count) + suffix; return; }
        var step = function (t) { if (!start) start = t; var p = Math.min((t - start) / 1200, 1);
            el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3))).toLocaleString() + suffix;
            if (p < 1) requestAnimationFrame(step); };
        requestAnimationFrame(step);
    };
    // Blocks rise into place only when they scroll into view. What is on screen at once, and
    // every page reached with Back / Forward or a reload, shows straight away in its place:
    // replaying the motion there looked like the page jumping.
    var nav = (window.performance && performance.getEntriesByType && performance.getEntriesByType('navigation')[0]) || {};
    var returning = nav.type === 'back_forward' || nav.type === 'reload';
    if ('IntersectionObserver' in window && !returning) {
        var io = new IntersectionObserver(function (entries) {
            entries.forEach(function (en) {
                if (!en.isIntersecting) return;
                en.target.classList.remove('reveal-pending');
                if (en.target.dataset.count) countUp(en.target);
                io.unobserve(en.target);
            });
        }, {rootMargin: '0px 0px -8% 0px'});
        var fold = window.innerHeight;
        document.querySelectorAll('[data-reveal], [data-count]').forEach(function (el) {
            if (el.hasAttribute('data-reveal') && el.getBoundingClientRect().top > fold) el.classList.add('reveal-pending');
            io.observe(el);
        });
    } else {
        document.querySelectorAll('[data-count]').forEach(function (el) { el.textContent = el.dataset.count; });
    }


    // Light that follows the cursor on primary buttons.
    document.addEventListener('pointermove', function (e) {
        var b = e.target.closest && e.target.closest('.btn-primary');
        if (!b) return;
        var r = b.getBoundingClientRect();
        b.style.setProperty('--mx', (e.clientX - r.left) + 'px');
        b.style.setProperty('--my', (e.clientY - r.top) + 'px');
    });
})();

/* Small behaviours without inline handlers (allowed by the Content-Security-Policy). */
document.addEventListener('click', function (e) {
    var toggle = e.target.closest('[data-toggle-hidden]');
    if (toggle) { var target = document.querySelector(toggle.dataset.toggleHidden); if (target) target.classList.toggle('hidden'); }
    var remover = e.target.closest('[data-remove-closest]');
    if (remover) { var box = remover.closest(remover.dataset.removeClosest); if (box) box.remove(); }
});
document.addEventListener('submit', function (e) {
    var form = e.target.closest('form[data-confirm]');
    if (form && !window.confirm(form.dataset.confirm)) e.preventDefault();
}, true);

/* Dropdowns (catalog pickers, make choice in the listing form): open/close, search,
   and for a choice made with radio buttons, show it on the button and close. */
document.querySelectorAll('[data-dropdown]').forEach(function (root) {
    var button = root.querySelector('[data-dropdown-button]');
    var panel = root.querySelector('[data-dropdown-panel]');
    var arrow = root.querySelector('[data-dropdown-arrow]');
    var search = root.querySelector('[data-dropdown-search]');
    var items = root.querySelectorAll('[data-dropdown-item]');
    var empty = root.querySelector('[data-dropdown-empty]');
    if (!button || !panel) return;
    function setOpen(open) {
        if (open) document.querySelectorAll('[data-dropdown-panel]').forEach(function (p) { if (p !== panel) p.classList.add('hidden'); });
        panel.classList.toggle('hidden', !open);
        if (arrow) arrow.classList.toggle('rotate-180', open);
        button.setAttribute('aria-expanded', open);
        if (open && search && window.matchMedia('(min-width: 640px)').matches) search.focus();
    }
    button.addEventListener('click', function () { setOpen(panel.classList.contains('hidden')); });
    document.addEventListener('click', function (e) { if (!root.contains(e.target)) setOpen(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setOpen(false); });
    if (search) search.addEventListener('input', function () {
        var q = search.value.trim().toLowerCase(), shown = 0;
        // Match from the start of the name or of any word in it: 'mer' finds Mercedes, not Hummer.
        items.forEach(function (a) {
            var name = a.dataset.dropdownItem;
            var ok = !q || (' ' + name.replace(/[-&/]/g, ' ')).indexOf(' ' + q) !== -1;
            a.classList.toggle('hidden', !ok); if (ok) shown++;
        });
        if (empty) empty.classList.toggle('hidden', shown > 0);
    });
    root.querySelectorAll('input[type=radio]').forEach(function (radio) {
        radio.addEventListener('change', function () {
            var option = radio.closest('[data-dropdown-item]'), value = root.querySelector('[data-dropdown-value]');
            if (option && value) value.innerHTML = option.querySelector('[data-option-face]').innerHTML;
            root.querySelectorAll('[data-dropdown-item]').forEach(function (o) { o.classList.toggle('is-active', o === option); });
            setOpen(false);
        });
    });
});

/* Listing form photos: picked files show as tiles with ✕ before saving (picking again adds
   more), saved photos are marked for removal with ✕, and a counter keeps within the limit. */
document.querySelectorAll('[data-photos]').forEach(function (box) {
    var input = box.querySelector('[data-photo-input]'), add = box.querySelector('[data-photo-add]');
    var grid = box.querySelector('[data-photo-grid]'), counter = box.querySelector('[data-photo-count]');
    var max = parseInt(box.dataset.max, 10) || 15, picked = [];
    var canEdit = true;
    try { new DataTransfer(); } catch (e) { canEdit = false; }  // very old browsers: plain input
    function saved() { return box.querySelectorAll('[data-photo-saved] input:not(:checked)').length; }
    function sync() {
        var total = saved() + (canEdit ? picked.length : input.files.length);
        counter.textContent = '· ' + total + ' / ' + max;
        counter.classList.toggle('text-red-400', total > max);
        add.classList.toggle('hidden', canEdit && total >= max);
    }
    function render() {
        grid.querySelectorAll('[data-photo-new]').forEach(function (t) { URL.revokeObjectURL(t.dataset.url); t.remove(); });
        picked.forEach(function (file, i) {
            var url = URL.createObjectURL(file), tile = document.createElement('div');
            tile.className = 'photo-tile'; tile.dataset.photoNew = ''; tile.dataset.url = url;
            var img = document.createElement('img'); img.src = url; img.alt = '';
            var x = document.createElement('button');
            x.type = 'button'; x.className = 'photo-remove'; x.setAttribute('aria-label', box.dataset.tRemove || 'Remove');
            x.innerHTML = '<span class="photo-remove-x">✕</span>';
            x.addEventListener('click', function () { picked.splice(i, 1); update(); });
            tile.appendChild(img); tile.appendChild(x);
            grid.insertBefore(tile, add);
        });
    }
    function update() {
        var dt = new DataTransfer();
        picked.forEach(function (f) { dt.items.add(f); });
        input.files = dt.files;
        render(); sync();
    }
    input.addEventListener('change', function () {
        if (!canEdit) { sync(); return; }
        var room = max - saved() - picked.length;
        Array.prototype.slice.call(input.files).forEach(function (f) {
            if (room > 0 && /^image\//.test(f.type || 'image/')) { picked.push(f); room--; }
        });
        update();
    });
    box.querySelectorAll('[data-photo-saved] input').forEach(function (c) { c.addEventListener('change', sync); });
    sync();
});

/* Site analytics (our own, see analytics/): a 'still here' ping while the page is open,
   for the live visitor count, and contact clicks on vehicle pages. No cookies. */
(function () {
    var body = document.body, pingUrl = body.dataset.aPing, eventUrl = body.dataset.aEvent, car = body.dataset.aCar || '';
    if (!pingUrl || !navigator.sendBeacon) return;
    function send(url, data) {
        var form = new FormData();
        Object.keys(data).forEach(function (k) { form.append(k, data[k]); });
        try { navigator.sendBeacon(url, form); } catch (e) { /* never break the page */ }
    }
    function ping() { if (document.visibilityState === 'visible') send(pingUrl, { path: location.pathname, car: car }); }
    ping();
    setInterval(ping, 45000);
    document.addEventListener('visibilitychange', ping);
    document.addEventListener('click', function (e) {
        var a = e.target.closest && e.target.closest('a[href]');
        if (!a) return;
        var href = a.getAttribute('href'), kind = '';
        if (/^tel:/i.test(href)) kind = 'phone';
        else if (/^https:\/\/(wa\.me|api\.whatsapp\.com)\//i.test(href)) kind = 'whatsapp';
        else if (/^https:\/\/(t\.me|telegram\.me)\//i.test(href)) kind = 'telegram';
        else if (/^mailto:/i.test(href)) kind = 'email';
        if (kind && car) send(eventUrl, { kind: kind, car: car });  // contacting a seller
    }, true);
})();

/* In-page links (All contacts, Back to top) scroll smoothly; page loads never do. */
document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href^="#"]');
    if (!a || a.getAttribute('href').length < 2) return;
    var id = a.getAttribute('href').slice(1);
    var target = id === 'top' ? document.body : document.getElementById(id);
    if (!target) return;
    e.preventDefault();
    var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (id === 'top') window.scrollTo({top: 0, behavior: reduce ? 'auto' : 'smooth'});
    else target.scrollIntoView({behavior: reduce ? 'auto' : 'smooth', block: 'start'});
    if (history.replaceState) history.replaceState(null, '', '#' + id);
});
