/** Tailwind scans these files for class names; the default theme is used. */
module.exports = {
  content: [
    './templates/**/*.html',
    './cars/templates/**/*.{html,txt}',
    './users/templates/**/*.{html,txt}',
    './assets/js/**/*.js',
    './cars/**/*.py',
    './users/**/*.py',
  ],
  // hover: effects only on devices with a real mouse; on phones a finger resting on a card
  // while scrolling counted as hover and zoomed its photo (looked like a glitch).
  future: { hoverOnlyWhenSupported: true },
  theme: { extend: {} },
  plugins: [],
};
