/**
 * Typeahead / autocomplete support for Atlassian resource inputs.
 *
 * Works with the typeahead_input Jinja2 macro which generates:
 *   - a visible search <input>  (class .ta-search-input)
 *   - a hidden <input>          (holds the selected ID for form submission)
 *   - a <ul> results container  (populated via HTMX swap)
 *
 * This module handles keyboard navigation, selection, and cleanup.
 * Debouncing is handled server-side by HTMX's delay:300ms trigger.
 */
(function () {
    'use strict';

    /**
     * Build the hx-get URL with the extra params baked in.
     * The macro puts the base endpoint in hx-get; we append &q=... via HTMX.
     * For extra query params (space, project), we bake them into hx-get.
     */
    function initWrapper(wrapper) {
        var searchInput = wrapper.querySelector('.ta-search-input');
        var resultsList = wrapper.querySelector('.typeahead-results');
        if (!searchInput || !resultsList) return;

        // Find the hidden input — it's the input[type=hidden] inside the wrapper
        var hiddenInput = wrapper.querySelector('input[type="hidden"]');
        if (!hiddenInput) return;

        // Already initialised?
        if (wrapper._taInit) return;
        wrapper._taInit = true;

        var activeIndex = -1;

        // -- Keyboard navigation --
        searchInput.addEventListener('keydown', function (e) {
            var items = resultsList.querySelectorAll('.ta-result');
            if (!items.length) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                activeIndex = Math.min(activeIndex + 1, items.length - 1);
                highlightItem(items);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                activeIndex = Math.max(activeIndex - 1, 0);
                highlightItem(items);
            } else if (e.key === 'Enter' && activeIndex >= 0) {
                e.preventDefault();
                selectItem(items[activeIndex]);
            } else if (e.key === 'Escape') {
                e.preventDefault();
                clearResults();
            }
        });

        // -- Clear hidden value when user edits the search field --
        searchInput.addEventListener('input', function () {
            if (searchInput.value === '') {
                hiddenInput.value = '';
            }
        });

        // -- Click on result --
        resultsList.addEventListener('click', function (e) {
            var item = e.target.closest('.ta-result');
            if (item) selectItem(item);
        });

        // -- Click outside to close --
        document.addEventListener('click', function (e) {
            if (!wrapper.contains(e.target)) {
                clearResults();
            }
        });

        function highlightItem(items) {
            items.forEach(function (el, i) {
                el.classList.toggle('ta-active', i === activeIndex);
            });
            if (items[activeIndex]) {
                items[activeIndex].scrollIntoView({ block: 'nearest' });
            }
        }

        function selectItem(item) {
            var value = item.getAttribute('data-value');
            var label = item.getAttribute('data-label') || item.textContent.trim();
            hiddenInput.value = value;
            searchInput.value = label;
            clearResults();
        }

        function clearResults() {
            resultsList.innerHTML = '';
            activeIndex = -1;
        }

        // Reset active index when new results arrive via HTMX
        resultsList.addEventListener('htmx:afterSwap', function () {
            activeIndex = -1;
        });
    }

    function initAll() {
        document.querySelectorAll('[data-typeahead]').forEach(initWrapper);
    }

    // Initialise on page load
    document.addEventListener('DOMContentLoaded', initAll);

    // Re-initialise after HTMX swaps in new content (e.g. partials with typeahead inputs)
    document.body.addEventListener('htmx:afterSettle', initAll);
})();
