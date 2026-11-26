(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.StoneVastPayouts = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  var STATUS_LABELS = {
    zh: {
      ok: '数据已更新',
      partial: '部分数据',
      stale: '缓存超期',
      error: '暂不可用',
      limited: '有限核验',
      unconfigured: '未配置',
      loading: '读取中'
    },
    en: {
      ok: 'Updated',
      partial: 'Partial data',
      stale: 'Cache stale',
      error: 'Unavailable',
      limited: 'Limited verification',
      unconfigured: 'Not configured',
      loading: 'Loading'
    }
  };

  function resolveLang(root) {
    var html = root && root.closest ? root.closest('html') : null;
    var lang = html ? html.getAttribute('lang') : '';
    return lang && lang.indexOf('en') === 0 ? 'en' : 'zh';
  }

  function resolveEndpoint(locationLike, override) {
    if (override) return override;
    if (locationLike && locationLike.hostname === 'haolinsong32-lang.github.io') {
      return 'https://stonevast.com/api/public/payouts';
    }
    return '/api/public/payouts';
  }

  function safeEvidenceUrl(url) {
    if (typeof url !== 'string' || !url.trim()) return null;
    try {
      var parsed = new URL(url.trim());
      return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? url.trim() : null;
    } catch (error) {
      return null;
    }
  }

  function present(value) {
    return value !== null && value !== undefined && value !== '';
  }

  function positive(value) {
    return present(value) && !/^0+(?:\.0+)?$/.test(String(value));
  }

  function amountText(value, symbol, hidden) {
    return !hidden && present(value) ? String(value) + ' ' + symbol : '--';
  }

  function hashrateText(value) {
    if (!present(value)) return '--';
    var number = Number(value);
    if (!isFinite(number) || number < 0) return '--';
    var units = ['H/s', 'kH/s', 'MH/s', 'GH/s', 'TH/s', 'PH/s'];
    var index = 0;
    while (number >= 1000 && index < units.length - 1) {
      number /= 1000;
      index += 1;
    }
    return number.toFixed(2) + ' ' + units[index];
  }

  function shortTxid(txid) {
    var value = typeof txid === 'string' && txid ? txid : '--';
    return value.length > 7 ? value.slice(0, 6) + '…' : value;
  }

  function timeText(value) {
    if (!present(value)) return '--';
    if (typeof value === 'number' || /^\d+(?:\.\d+)?$/.test(String(value))) {
      var date = new Date(Number(value) * 1000);
      if (!isNaN(date.getTime())) return date.toISOString();
    }
    return String(value);
  }

  function buildPayoutView(payload, lang) {
    var source = payload && typeof payload === 'object' ? payload : {};
    var labels = STATUS_LABELS[lang === 'en' ? 'en' : 'zh'];
    var state = labels[source.status] ? source.status : 'partial';
    var assets = Array.isArray(source.assets) ? source.assets : [];

    var viewAssets = assets.map(function (item) {
      var asset = item && typeof item === 'object' ? item : {};
      var symbol = String(asset.asset || asset.chain || '--');
      var hidden = asset.status === 'unconfigured' || asset.status === 'error';
      var reference = asset.reference && typeof asset.reference === 'object' ? asset.reference : {};
      var pool = asset.pool && typeof asset.pool === 'object' ? asset.pool : null;
      return Object.assign({}, asset, {
        symbol: symbol,
        todayText: amountText(asset.today, symbol, hidden),
        confirmedText: amountText(asset.confirmed, symbol, hidden),
        pendingText: amountText(asset.pending, symbol, hidden),
        limitedText: amountText(asset.limitedTotal, symbol, hidden),
        usdtText: present(reference.usdt) ? String(reference.usdt) + ' USDT' : '--',
        cnyText: present(reference.cny) ? String(reference.cny) + ' CNY' : '--',
        statusLabel: labels[asset.status] || labels.partial,
        hasLimited: positive(asset.limitedTotal),
        pool: pool,
        poolUnpaidText: pool ? amountText(pool.unpaid, symbol, hidden) : '--',
        poolUnconfirmedText: pool ? amountText(pool.unconfirmed, symbol, hidden) : '--',
        poolReportedPaidText: pool ? amountText(pool.reportedPaid, symbol, hidden) : '--',
        poolHashrateText: pool ? hashrateText(pool.hashrate) : '--',
        poolHashrate24hText: pool ? hashrateText(pool.hashrate24h) : '--',
        poolLastShareText: pool ? timeText(pool.lastShareAt) : '--',
        poolObservedText: pool ? timeText(pool.observedAt) : '--'
      });
    });

    var configured = viewAssets.filter(function (asset) {
      return asset.status !== 'unconfigured' && asset.status !== 'error';
    });
    var events = Array.isArray(source.events) ? source.events : [];
    var latest = events.length ? events[0] : null;
    var limited = viewAssets.some(function (asset) { return asset.hasLimited; });
    var visualState = state === 'partial' && limited ? 'limited' : state;

    return {
      state: state,
      visualState: visualState,
      statusLabel: labels[visualState],
      generatedAt: source.generatedAt || null,
      refreshSeconds: source.refreshSeconds || 600,
      timezone: source.timezone || null,
      assets: viewAssets,
      events: events,
      quotes: Array.isArray(source.quotes) ? source.quotes : [],
      messages: Array.isArray(source.messages) ? source.messages : [],
      todayText: configured.length ? configured.map(function (asset) { return asset.todayText; }).join(' · ') : '--',
      totalText: configured.length ? configured.map(function (asset) { return asset.confirmedText; }).join(' · ') : '--',
      latestText: latest ? String(latest.asset || latest.chain || '--') + ' · ' + shortTxid(latest.txid) : '--',
      latestAmountText: latest ? (latest.verification === 'limited' || !present(latest.amount) ? (lang === 'en' ? 'Limited verification' : '金额有限核验') : String(latest.amount) + ' ' + String(latest.asset || latest.chain || '')) : '--',
      latestEvidenceUrl: latest ? safeEvidenceUrl(latest.explorerUrl) : null
    };
  }

  function setSlot(root, selector, value) {
    var node = root.querySelector(selector);
    if (node) node.textContent = value;
  }

  function cell(documentLike, value) {
    var node = documentLike.createElement('td');
    node.textContent = value;
    return node;
  }

  function emptyRow(documentLike, columns, message) {
    var row = documentLike.createElement('tr');
    var node = cell(documentLike, message);
    node.setAttribute('colspan', columns);
    row.appendChild(node);
    return row;
  }

  function renderPayoutView(root, view, documentLike) {
    var lang = resolveLang(root);
    root.setAttribute('data-state', view.visualState);
    var status = root.querySelector('[data-payout-status]');
    if (status) {
      status.textContent = view.statusLabel;
      status.setAttribute('data-state', view.visualState);
    }
    setSlot(root, '[data-payout-today]', view.todayText);
    setSlot(root, '[data-payout-total]', view.totalText);
    setSlot(root, '[data-payout-latest]', view.latestText);
    setSlot(root, '[data-payout-latest-amount]', view.latestAmountText);
    setSlot(root, '[data-payout-generated]', view.generatedAt || '--');

    var message = view.messages.map(function (item) {
      if (item && typeof item === 'object') return present(item.message) ? String(item.message) : String(item.code || '');
      return present(item) ? String(item) : '';
    }).filter(Boolean).join('；');
    var hasConfigured = view.assets.some(function (asset) {
      return asset.status !== 'unconfigured' && asset.status !== 'error';
    });
    if (view.state === 'error') message = lang === 'en' ? 'Read-only endpoint temporarily unavailable; historical snapshots are not used as substitutes.' : '只读接口暂时不可用；未使用历史快照补值。';
    else if (!view.assets.length) message = lang === 'en' ? 'The endpoint returned no public assets; verified receipts show --.' : '接口未返回公开资产；实际到账显示 --。';
    else if (!hasConfigured) message = lang === 'en' ? 'Public addresses are not configured yet; no income amounts are shown.' : '公开地址尚未配置，当前不展示收入金额。';
    setSlot(root, '[data-payout-message]', message);

    var assetBody = root.querySelector('[data-payout-assets]');
    if (assetBody) {
      var rows = view.assets.map(function (asset) {
        var row = documentLike.createElement('tr');
        row.appendChild(cell(documentLike, asset.symbol));
        row.appendChild(cell(documentLike, asset.todayText));
        row.appendChild(cell(documentLike, asset.confirmedText));
        row.appendChild(cell(documentLike, asset.pendingText));
        row.appendChild(cell(documentLike, asset.hasLimited ? asset.limitedText : '--'));
        row.appendChild(cell(documentLike, asset.usdtText + ' / ' + asset.cnyText));
        row.appendChild(cell(documentLike, asset.statusLabel));
        return row;
      });
      if (!rows.length) rows.push(emptyRow(documentLike, 7, lang === 'en' ? 'No public assets to display yet.' : '暂无可显示的公开资产。'));
      assetBody.replaceChildren.apply(assetBody, rows);
    }

    var poolBody = root.querySelector('[data-payout-pools]');
    if (poolBody) {
      var poolRows = view.assets.map(function (asset) {
        var row = documentLike.createElement('tr');
        row.appendChild(cell(documentLike, asset.symbol));
        row.appendChild(cell(documentLike, asset.poolUnpaidText));
        row.appendChild(cell(documentLike, asset.poolUnconfirmedText));
        row.appendChild(cell(documentLike, asset.poolReportedPaidText));
        row.appendChild(cell(documentLike, asset.poolHashrateText));
        row.appendChild(cell(documentLike, asset.poolHashrate24hText));
        row.appendChild(cell(documentLike, asset.poolLastShareText));
        row.appendChild(cell(documentLike, asset.poolObservedText));
        row.appendChild(cell(documentLike, asset.pool ? String(asset.pool.source || '--') : '--'));
        return row;
      });
      if (!poolRows.length) poolRows.push(emptyRow(documentLike, 9, lang === 'en' ? 'No pool status yet; never used to infer actual receipts.' : '暂无矿池状态；不会据此推定实际到账。'));
      poolBody.replaceChildren.apply(poolBody, poolRows);
    }

    var eventBody = root.querySelector('[data-payout-events]');
    if (eventBody) {
      var eventRows = view.events.map(function (event) {
        var row = documentLike.createElement('tr');
        var symbol = String(event.asset || event.chain || '--');
        row.appendChild(cell(documentLike, event.occurredAt || event.blockTime || '--'));
        row.appendChild(cell(documentLike, symbol));
        row.appendChild(cell(documentLike, present(event.amount) ? String(event.amount) + ' ' + symbol : (lang === 'en' ? 'Limited verification' : '金额有限核验')));
        var evidence = documentLike.createElement('td');
        var url = safeEvidenceUrl(event.explorerUrl);
        if (url) {
          var link = documentLike.createElement('a');
          link.textContent = shortTxid(event.txid);
          link.setAttribute('href', url);
          link.setAttribute('target', '_blank');
          link.setAttribute('rel', 'noopener noreferrer');
          evidence.appendChild(link);
        } else {
          evidence.textContent = shortTxid(event.txid);
        }
        row.appendChild(evidence);
        row.appendChild(cell(documentLike, event.status || '--'));
        return row;
      });
      if (!eventRows.length) eventRows.push(emptyRow(documentLike, 5, lang === 'en' ? 'No public receipt events yet.' : '暂无公开到账事件。'));
      eventBody.replaceChildren.apply(eventBody, eventRows);
    }

    var quoteBody = root.querySelector('[data-payout-quotes]');
    if (quoteBody) {
      var quoteRows = view.quotes.map(function (quote) {
        var row = documentLike.createElement('tr');
        var path = Array.isArray(quote.path) && quote.path.length ? quote.path.join(' → ') : (quote.pair || '--');
        row.appendChild(cell(documentLike, path));
        row.appendChild(cell(documentLike, present(quote.rate) ? String(quote.rate) : '--'));
        row.appendChild(cell(documentLike, quote.source || '--'));
        row.appendChild(cell(documentLike, timeText(quote.quoteTime)));
        row.appendChild(cell(documentLike, timeText(quote.observedAt)));
        row.appendChild(cell(documentLike, quote.quoteId || '--'));
        return row;
      });
      if (!quoteRows.length) quoteRows.push(emptyRow(documentLike, 6, lang === 'en' ? 'No quotes available yet; reference conversions show --.' : '暂无可用报价；参考折算显示 --。'));
      quoteBody.replaceChildren.apply(quoteBody, quoteRows);
    }
  }

  async function mountPayouts(root, options) {
    var opts = options || {};
    var documentLike = opts.document || (typeof document !== 'undefined' ? document : null);
    var locationLike = opts.location || (typeof location !== 'undefined' ? location : null);
    var fetcher = opts.fetch || (typeof fetch !== 'undefined' ? fetch : null);
    var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timeoutMs = opts.timeoutMs === undefined ? 12000 : opts.timeoutMs;
    var timer = null;
    var view;

    if (controller && timeoutMs > 0) timer = setTimeout(function () { controller.abort(); }, timeoutMs);
    try {
      if (!fetcher) throw new Error('fetch unavailable');
      var response = await fetcher(resolveEndpoint(locationLike, opts.endpoint), {
        method: 'GET',
        credentials: 'omit',
        cache: 'no-store',
        headers: { Accept: 'application/json' },
        signal: controller ? controller.signal : undefined
      });
      if (!response || !response.ok) throw new Error('payout endpoint unavailable');
      view = buildPayoutView(await response.json(), resolveLang(root));
    } catch (error) {
      view = buildPayoutView({ status: 'error', assets: [], events: [], quotes: [], messages: [] }, resolveLang(root));
    } finally {
      if (timer) clearTimeout(timer);
    }

    if (root && documentLike) renderPayoutView(root, view, documentLike);
    var schedule = opts.schedule || (typeof setTimeout !== 'undefined' ? setTimeout : null);
    if (schedule && opts.poll !== false) {
      schedule(function () { mountPayouts(root, opts); }, Number(view.refreshSeconds) * 1000);
    }
    return view;
  }

  return {
    resolveEndpoint: resolveEndpoint,
    buildPayoutView: buildPayoutView,
    renderPayoutView: renderPayoutView,
    safeEvidenceUrl: safeEvidenceUrl,
    mountPayouts: mountPayouts
  };
});
