// Rewrites server-rendered <time datetime="UTC-ISO" data-localize="..."> elements
// to the browser's local timezone using Intl.DateTimeFormat.
//
// Loaded site-wide via `web_include_js` in hooks.py. Server-side templates emit
// timestamps via the `local_datetime` / `local_date` macros in
// `templates/includes/portal_localize.html`. The fallback text inside each
// <time> element is what the server formatted; if JS fails to load or the
// datetime attribute is unparseable, the user just sees the server-formatted
// value (in system tz). This script is non-blocking and idempotent.
//
// Supported `data-localize` formats:
//   - "datetime"       full date + time (default; matches Frappe format_datetime)
//   - "datetime_short" date + HH:mm only (no seconds, no day-of-week)
//   - "date"           date-only
//   - "time"           time-of-day only
//
// Localization uses the visitor's browser locale (`navigator.language`) and
// timezone (resolved via Intl). No user profile lookup needed.

(function () {
  'use strict';

  function safeFormat(date, options) {
    try {
      return new Intl.DateTimeFormat(navigator.language || 'en-GB', options).format(date);
    } catch (e) {
      // Should never happen, but if Intl is unavailable just stringify.
      return date.toString();
    }
  }

  var FORMATS = {
    datetime: {
      year: 'numeric', month: 'short', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false,
    },
    datetime_short: {
      year: 'numeric', month: 'short', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
      hour12: false,
    },
    date: {
      year: 'numeric', month: 'short', day: '2-digit',
    },
    time: {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false,
    },
  };

  function hydrate(root) {
    var nodes = (root || document).querySelectorAll('time[datetime][data-localize]');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.dataset.localized === '1') continue;  // idempotent guard
      var iso = el.getAttribute('datetime');
      if (!iso) continue;
      var d = new Date(iso);
      if (isNaN(d.getTime())) continue;  // leave server text alone
      var format = el.getAttribute('data-localize') || 'datetime';
      var opts = FORMATS[format] || FORMATS.datetime;
      var formatted = safeFormat(d, opts);
      el.textContent = formatted;
      el.title = d.toString();  // hover gives the full browser-locale string
      el.dataset.localized = '1';
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { hydrate(); });
  } else {
    hydrate();
  }

  // Expose for any dynamic content that injects timestamps after load.
  window.portalLocalizeTime = hydrate;
})();
