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
            }).join('') + '<a class="search-all" href="' + esc(data.all_url) + '"><span>' + T.all + ' (' + data.total + ')</span><span aria-hidden="true">→</span></a>';
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
    onScroll(); window.addEventListener('scroll', onScroll, {passive: true});

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
    if ('IntersectionObserver' in window) {
        var io = new IntersectionObserver(function (entries) {
            entries.forEach(function (en) {
                if (!en.isIntersecting) return;
                en.target.classList.add('is-visible');
                if (en.target.dataset.count) countUp(en.target);
                io.unobserve(en.target);
            });
        }, {rootMargin: '0px 0px -8% 0px'});
        document.querySelectorAll('[data-reveal], [data-count]').forEach(function (el) { io.observe(el); });
    } else {
        document.querySelectorAll('[data-reveal]').forEach(function (el) { el.classList.add('is-visible'); });
    }

    // Photos fade in when loaded.
    document.querySelectorAll('img.fade-in').forEach(function (img) {
        var done = function () { img.classList.add('is-loaded'); };
        if (img.complete) done(); else { img.addEventListener('load', done); img.addEventListener('error', done); }
    });

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
