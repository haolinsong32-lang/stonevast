(function () {
  'use strict';
  document.documentElement.classList.add('js');

  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var revealItems = document.querySelectorAll('.site-reveal');
  if (!reduceMotion && 'IntersectionObserver' in window && revealItems.length) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    revealItems.forEach(function (item) { observer.observe(item); });
  } else {
    revealItems.forEach(function (item) { item.classList.add('is-visible'); });
  }

  var toggle = document.querySelector('[data-nav-toggle]');
  var nav = document.getElementById('primary-nav');
  if (toggle && nav) {
    var close = function () {
      nav.removeAttribute('data-open');
      toggle.setAttribute('aria-expanded', 'false');
    };
    toggle.addEventListener('click', function () {
      var open = nav.getAttribute('data-open') === 'true';
      if (open) {
        close();
      } else {
        nav.setAttribute('data-open', 'true');
        toggle.setAttribute('aria-expanded', 'true');
      }
    });
    nav.addEventListener('click', function (event) {
      if (event.target.closest('a')) close();
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') close();
    });
  }

  var parallaxItems = document.querySelectorAll('[data-parallax]');
  if (!reduceMotion && parallaxItems.length) {
    var ticking = false;
    var updateParallax = function () {
      parallaxItems.forEach(function (item) {
        var rect = item.parentElement.getBoundingClientRect();
        if (rect.bottom < 0 || rect.top > window.innerHeight) return;
        var offset = Math.max(0, Math.min(48, -rect.top * 0.08));
        item.style.setProperty('--parallax-y', offset.toFixed(2) + 'px');
      });
      ticking = false;
    };
    var requestParallax = function () {
      if (!ticking) {
        window.requestAnimationFrame(updateParallax);
        ticking = true;
      }
    };
    window.addEventListener('scroll', requestParallax, { passive: true });
    window.addEventListener('resize', requestParallax);
    updateParallax();
  }

  var analyticsEndpoint = 'https://stonevast.com/api/event';
  var analyticsPath = window.location.pathname || '/';
  if (analyticsPath.indexOf('/stonevast/') === 0) analyticsPath = analyticsPath.slice(10);
  if (analyticsPath === '/stonevast') analyticsPath = '/';
  var allowedClicks = {
    download_bat: true,
    telegram_click: true,
    official_download_click: true,
    copy_wallet_click: true
  };
  var newEventId = function () {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (char) {
      var random = Math.random() * 16 | 0;
      var value = char === 'x' ? random : (random & 3 | 8);
      return value.toString(16);
    });
  };
  var sendAnalytics = function (name) {
    var payload = JSON.stringify({
      eventId: newEventId(),
      name: name,
      path: analyticsPath
    });
    var sent = false;
    try {
      if (navigator.sendBeacon) {
        sent = navigator.sendBeacon(
          analyticsEndpoint,
          new Blob([payload], { type: 'text/plain;charset=UTF-8' })
        );
      }
      if (!sent) {
        window.fetch(analyticsEndpoint, {
          method: 'POST',
          body: payload,
          headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
          keepalive: true
        }).catch(function () {});
      }
    } catch (error) {}
  };
  sendAnalytics('pageview');
  window.svReportDownload = function () { sendAnalytics('download_bat'); };
  document.addEventListener('click', function (event) {
    var link = event.target.closest && event.target.closest('a[href]');
    if (!link) return;
    var name = link.getAttribute('data-analytics-event') || '';
    if (!name && /^https:\/\/t\.me\//.test(link.href)) name = 'telegram_click';
    if (!name && /^https:\/\/github\.com\/.+\/releases/.test(link.href)) {
      name = 'official_download_click';
    }
    if (allowedClicks[name]) sendAnalytics(name);
  });

  var refreshStats = function () {
    if (!document.getElementById('vPv') && !document.getElementById('vUv')) return;
    window.fetch('https://stonevast.com/api/stats', { cache: 'no-store' })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        if (!data) return;
        var pv = document.getElementById('vPv');
        var uv = document.getElementById('vUv');
        if (pv) pv.textContent = data.pv;
        if (uv) uv.textContent = data.uv;
      }).catch(function () {});
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', refreshStats, { once: true });
  } else {
    refreshStats();
  }
  window.setInterval(refreshStats, 60000);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) refreshStats();
  });
}());
