// Small, framework-free progressive enhancements. Every page works from
// plain links and form submissions without this file; it only smooths a
// few interactions that the retired React frontend handled client-side.
(function () {
  'use strict';

  // Auto-grow the issue textarea as the visitor types (was a layout effect
  // in the old React composer).
  document.querySelectorAll('[data-autogrow]').forEach(function (field) {
    var resize = function () {
      field.style.height = 'auto';
      field.style.height = Math.min(field.scrollHeight, 240) + 'px';
    };
    field.addEventListener('input', resize);
    resize();
  });

  // Cmd/Ctrl+Enter submits the enclosing form.
  document.querySelectorAll('[data-submit-on-mod-enter]').forEach(function (field) {
    field.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        field.form && field.form.requestSubmit();
      }
    });
  });

  // Re-submit a GET form as soon as one of its controls changes, so a sort
  // dropdown re-orders the page without a separate "Apply" button.
  document.querySelectorAll('[data-submit-on-change]').forEach(function (field) {
    field.addEventListener('change', function () {
      field.form && field.form.requestSubmit();
    });
  });

  // Filter a sentiment breakdown down to one group at a time. Every item
  // stays in the DOM (so it still works with JS disabled, just unfiltered);
  // this only toggles visibility and the surrounding summary text.
  document.querySelectorAll('[data-sentiment-breakdown]').forEach(function (root) {
    var buttons = root.querySelectorAll('[data-sentiment-filter]');
    var items = root.querySelectorAll('[data-sentiment-item]');
    var resetButtons = root.querySelectorAll('[data-sentiment-reset]');
    var summary = root.querySelector('[data-sentiment-summary]');
    var groupLabels = {};
    buttons.forEach(function (button) {
      groupLabels[button.getAttribute('data-sentiment-filter')] = button.getAttribute('data-sentiment-label');
    });

    function apply(selected) {
      buttons.forEach(function (button) {
        var isSelected = button.getAttribute('data-sentiment-filter') === selected;
        button.classList.toggle('is-current', isSelected);
        button.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
      });
      var visibleCount = 0;
      items.forEach(function (item) {
        var matches = !selected || item.getAttribute('data-sentiment-item') === selected;
        item.classList.toggle('search-hidden', !matches);
        if (matches) visibleCount += 1;
      });
      resetButtons.forEach(function (button) {
        button.classList.toggle('search-hidden', !selected);
      });
      if (summary) {
        var label = selected ? groupLabels[selected] : 'All views';
        summary.textContent = label + ' · ' + visibleCount + ' opinion' + (visibleCount === 1 ? '' : 's');
      }
    }

    buttons.forEach(function (button) {
      button.addEventListener('click', function () {
        var value = button.getAttribute('data-sentiment-filter');
        var isCurrent = button.classList.contains('is-current');
        apply(isCurrent ? null : value);
      });
    });
    resetButtons.forEach(function (button) {
      button.addEventListener('click', function () { apply(null); });
    });
  });
})();
