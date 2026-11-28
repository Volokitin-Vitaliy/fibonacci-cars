/* Vehicle page on phones: the contact bar shows whenever the price box is out of view
   (above it, while looking at the photos, and below it). When the page opens the bar is
   simply in place (no slide-in); later it fades in and out softly. */
(function () {
    var bar = document.querySelector('[data-contact-bar]'), box = document.querySelector('[data-price-box]');
    if (!bar || !box || !window.IntersectionObserver) return;
    var first = true;
    new IntersectionObserver(function (entries) {
        var hidden = !entries[entries.length - 1].isIntersecting;
        if (first) bar.classList.add('no-motion');
        bar.classList.toggle('is-visible', hidden);
        bar.setAttribute('aria-hidden', hidden ? 'false' : 'true');
        bar.querySelectorAll('a').forEach(function (a) { a.tabIndex = hidden ? 0 : -1; });
        if (first) {
            first = false;
            bar.getBoundingClientRect();  // apply the state before motion is turned back on
            requestAnimationFrame(function () { bar.classList.remove('no-motion'); });
        }
    }, {rootMargin: '-40px 0px'}).observe(box);  // a small margin: no flicker at the edge
})();
