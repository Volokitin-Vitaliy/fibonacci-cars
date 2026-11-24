/* Vehicle page on phones: the contact bar shows whenever the price box is out of view
   (above it, while looking at the photos, and below it). */
(function () {
    var bar = document.querySelector('[data-contact-bar]'), box = document.querySelector('[data-price-box]');
    if (!bar || !box || !window.IntersectionObserver) return;
    new IntersectionObserver(function (entries) {
        var hidden = !entries[0].isIntersecting;
        bar.classList.toggle('is-visible', hidden);
        bar.setAttribute('aria-hidden', hidden ? 'false' : 'true');
        bar.querySelectorAll('a').forEach(function (a) { a.tabIndex = hidden ? 0 : -1; });
    }).observe(box);
})();
