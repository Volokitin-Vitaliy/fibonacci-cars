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
  theme: { extend: {} },
  plugins: [],
};
