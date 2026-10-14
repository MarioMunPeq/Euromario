/**
 * EuroMario — frontend app
 * Vanilla JS. Fetch → filter → render. No dependencies.
 *
 * State model: one game filter + one section filter, both optional,
 * mirrored in the URL (?game=&section=).
 */

'use strict';

// ══════════════════════════════════════════════════════════════
// Configuration
// ══════════════════════════════════════════════════════════════

const CONFIG = {
  dataUrl: 'data/news.json',
  gamesUrl: 'data/games.json',
  // Games surfaced in the top bar, in this order.
  featuredGames: ['Grand Theft Auto', 'Pokemon'],
  labels: {
    'Grand Theft Auto': 'GTA',
    Pokemon: 'Pokémon',
  },
  // Logos that ship as solid black glyphs and need inverting on a dark bar.
  // Logos that already carry light pixels (e.g. GTA) must NOT be inverted.
  darkLogos: new Set(['Pokemon']),
  // Cap the stagger so late cards don't wait seconds to appear.
  maxStagger: 14,
};

const SECTIONS = ['all', 'news', 'rumors'];

// ══════════════════════════════════════════════════════════════
// State
// ══════════════════════════════════════════════════════════════

const state = {
  news: [],
  logos: {},
  game: null,
  section: 'all',
};

let els = {};

// ══════════════════════════════════════════════════════════════
// Helpers
// ══════════════════════════════════════════════════════════════

const escapeHtml = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));

const formatDate = (value) =>
  new Date(value).toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
  });

const formatStamp = (value) =>
  new Date(value).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });

const gameLabel = (name) => CONFIG.labels[name] || name;

const sourceName = (item) => {
  const raw = typeof item.source === 'string' ? item.source : item.source?.name;
  return raw || 'Unknown';
};

const sourceType = (item) =>
  item.source_type ?? item.source?.type ?? 'media';

const sourceInitials = (name) => {
  const words = name.replace(/\s*·\s*.+$/, '').trim().split(/\s+/);
  if (words.length === 1) return words[0].slice(0, 3).toUpperCase();
  return words.slice(0, 3).map((w) => w[0]).join('').toUpperCase();
};

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

// ══════════════════════════════════════════════════════════════
// Data
// ══════════════════════════════════════════════════════════════

async function fetchJson(url) {
  const res = await fetch(`${url}?v=${Date.now()}`, {
    cache: 'no-store',
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function loadNews() {
  const data = await fetchJson(CONFIG.dataUrl);
  if (!Array.isArray(data?.news)) throw new Error('Malformed news payload');
  return data;
}

async function loadLogos() {
  try {
    const data = await fetchJson(CONFIG.gamesUrl);
    const logos = {};
    for (const game of data?.games ?? []) {
      if (game?.name && game?.logo) logos[game.name] = `assets/games/${game.logo}`;
    }
    return logos;
  } catch {
    return {}; // Logos are decorative; never block content on them.
  }
}

// ══════════════════════════════════════════════════════════════
// Filtering
// ══════════════════════════════════════════════════════════════

function visibleNews() {
  return state.news.filter((item) => {
    if (state.game && item.game !== state.game) return false;
    if (state.section === 'news' && item.category === 'rumor') return false;
    if (state.section === 'rumors' && item.category !== 'rumor') return false;
    return true;
  });
}

// ══════════════════════════════════════════════════════════════
// Rendering — cards
// ══════════════════════════════════════════════════════════════

function renderMedia(item) {
  const scrim = `
    <div class="card__scrim">
      <p class="card__game"><span>${escapeHtml(item.game || 'Gaming')}</span></p>
    </div>`;

  if (item.image) {
    return `
      <div class="card__media">
        <img class="card__img" src="${escapeHtml(item.image)}" alt="" loading="lazy" decoding="async"
             data-initials="${escapeHtml(sourceInitials(sourceName(item)))}">
        ${scrim}
      </div>`;
  }

  const placeholder = sourceType(item) === 'reddit'
    ? `<img class="card__fallback-logo" src="assets/icons/reddit.svg" alt="" aria-hidden="true">`
    : `<span class="card__fallback-initials">${escapeHtml(sourceInitials(sourceName(item)))}</span>`;

  return `
    <div class="card__media">
      <div class="card__fallback${sourceType(item) === 'reddit' ? ' card__fallback--reddit' : ''}">
        ${placeholder}
      </div>
      ${scrim}
    </div>`;
}

function renderCard(item, index) {
  const published = new Date(item.published_at);
  const meta = `
    <p class="card__meta">
      <span class="card__source">${escapeHtml(sourceName(item))}</span>
      <span class="card__meta-dot">·</span>
      <time datetime="${published.toISOString()}">${formatDate(published)}</time>
    </p>`;

  const summary = item.summary
    ? `<p class="card__summary">${escapeHtml(item.summary)}</p>`
    : '';

  return `
    <article class="card" data-category="${escapeHtml(item.category || 'news')}" style="--i:${Math.min(index, CONFIG.maxStagger)}">
      ${renderMedia(item)}
      <div class="card__body">
        ${meta}
        <h3 class="card__title">
          <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a>
        </h3>
        ${summary}
      </div>
    </article>`;
}

/** Fade in images as they decode; swap to the initials block if one 404s. */
function hydrateImages(scope) {
  scope.querySelectorAll('.card__img').forEach((img) => {
    const settle = (ok) => {
      if (!ok) {
        const media = img.closest('.card__media');
        if (media) {
          media.querySelector('.card__img')?.remove();
          const fallback = document.createElement('div');
          fallback.className = 'card__fallback';
          const initials = document.createElement('span');
          initials.className = 'card__fallback-initials';
          initials.textContent = img.dataset.initials || '?';
          fallback.append(initials);
          media.prepend(fallback);
        }
        return;
      }
      img.classList.add('is-loaded');
    };

    if (img.complete) {
      settle(img.naturalWidth > 0);
    } else {
      img.addEventListener('load', () => settle(true), { once: true });
      img.addEventListener('error', () => settle(false), { once: true });
    }
  });
}

function renderGrid(items) {
  els.grid.innerHTML = items.map(renderCard).join('');
  hydrateImages(els.grid);
  syncToolbar(items.length);
}

// ══════════════════════════════════════════════════════════════
// Rendering — toolbar
// ══════════════════════════════════════════════════════════════

function activeFilterLabels() {
  const labels = [];
  if (state.game) labels.push(gameLabel(state.game));
  if (state.section !== 'all') labels.push(state.section === 'news' ? 'News' : 'Rumors');
  return labels;
}

function syncToolbar(count) {
  const labels = activeFilterLabels();
  const scope = state.section === 'all' ? '' : ` · ${state.section}`;

  els.count.innerHTML = `<b>${count}</b> ${count === 1 ? 'story' : 'stories'}${scope}`;

  const hasFilters = labels.length > 0;
  els.toolbar.hidden = false;
  els.clear.hidden = !hasFilters;
  els.clearLabel.textContent = hasFilters ? labels.join(' · ') : 'Clear filters';
  els.emptyReset.hidden = !hasFilters;
  els.emptyReset.textContent = hasFilters ? `Clear ${labels.join(' · ')}` : 'Clear filters';
}

// ══════════════════════════════════════════════════════════════
// Rendering — controls
// ══════════════════════════════════════════════════════════════

function renderGameFilters(availableGames) {
  const games = CONFIG.featuredGames.filter((g) => availableGames.has(g) || state.logos[g]);
  if (!games.length) return;

  els.gameFilters.innerHTML = games.map((game) => {
    const logo = state.logos[game];
    const mark = logo
      ? `<img class="gamefilter__mark${CONFIG.darkLogos.has(game) ? ' gamefilter__mark--invert' : ''}" src="${escapeHtml(logo)}" alt="" aria-hidden="true" width="34" height="34">`
      : `<span class="gamefilter__mark" aria-hidden="true"></span>`;
    return `
      <button type="button" class="gamefilter" data-game="${escapeHtml(game)}"
              aria-pressed="false" aria-label="${escapeHtml(gameLabel(game))}">
        ${mark}
      </button>`;
  }).join('');

  els.gameFilters.hidden = false;
}

function syncControls() {
  document.querySelectorAll('.gamefilter').forEach((btn) => {
    btn.setAttribute('aria-pressed', String(btn.dataset.game === state.game));
  });

  els.sectionButtons.forEach((btn) => {
    btn.setAttribute('aria-checked', String(btn.dataset.section === state.section));
  });
}

// ══════════════════════════════════════════════════════════════
// State views
// ══════════════════════════════════════════════════════════════

function showView(view) {
  els.loading.hidden = view !== 'loading';
  els.error.hidden = view !== 'error';
  els.empty.hidden = view !== 'empty';
  els.grid.hidden = view !== 'content';
  els.toolbar.hidden = view === 'loading' || view === 'error';
}

function showError(message, title) {
  els.errorTitle.textContent = title;
  els.errorMessage.textContent = message;
  showView('error');
}

// ══════════════════════════════════════════════════════════════
// Apply / sync
// ══════════════════════════════════════════════════════════════

function apply() {
  const items = visibleNews();
  if (!items.length) {
    els.grid.innerHTML = '';
    hydrateImages(els.grid);
    syncToolbar(0);
    showView('empty');
  } else {
    renderGrid(items);
    showView('content');
  }
  syncControls();
}

function writeUrl() {
  const params = new URLSearchParams();
  if (state.game) params.set('game', state.game);
  if (state.section !== 'all') params.set('section', state.section);
  const query = params.toString();
  history.replaceState(null, '', query ? `${location.pathname}?${query}` : location.pathname);
}

function readUrl() {
  const params = new URLSearchParams(location.search);
  const game = params.get('game');
  const section = params.get('section');

  state.game = game || null;
  state.section = SECTIONS.includes(section) ? section : 'all';
}

function resetFilters() {
  state.game = null;
  state.section = 'all';
  apply();
  writeUrl();
}

// ══════════════════════════════════════════════════════════════
// Events
// ══════════════════════════════════════════════════════════════

function bindEvents() {
  els.gameFilters.addEventListener('click', (e) => {
    const btn = e.target.closest('.gamefilter');
    if (!btn) return;
    state.game = state.game === btn.dataset.game ? null : btn.dataset.game;
    apply();
    writeUrl();
  });

  els.sectionButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      state.section = state.section === btn.dataset.section ? 'all' : btn.dataset.section;
      apply();
      writeUrl();
    });
  });

  els.retry.addEventListener('click', boot);
  els.clear.addEventListener('click', resetFilters);
  els.emptyReset.addEventListener('click', resetFilters);

  window.addEventListener('popstate', () => {
    readUrl();
    apply();
  });
}

// ══════════════════════════════════════════════════════════════
// Boot
// ══════════════════════════════════════════════════════════════

function renderFooterStamp(generatedAt) {
  if (!generatedAt) return;
  els.footerUpdated.textContent = `Updated ${formatStamp(generatedAt)}`;
}

async function boot() {
  showView('loading');

  try {
    const [news, logos] = await Promise.all([loadNews(), loadLogos()]);
    state.news = news.news;
    state.logos = logos;

    renderFooterStamp(news.generated_at);
    renderGameFilters(new Set(state.news.map((n) => n.game)));
    readUrl();
    apply();
  } catch (err) {
    showError(
      String(err.message || err).includes('404')
        ? 'The digest has not been generated yet. Check back shortly.'
        : 'Could not reach the digest. Check your connection and try again.',
      'Failed to load news',
    );
  }
}

function init() {
  els = {
    gameFilters: document.getElementById('game-filters'),
    sectionButtons: document.querySelectorAll('.segments__btn'),
    toolbar: document.getElementById('toolbar'),
    count: document.getElementById('toolbar-count'),
    clear: document.getElementById('clear-filters'),
    clearLabel: document.getElementById('clear-filters-label'),
    loading: document.getElementById('state-loading'),
    error: document.getElementById('state-error'),
    errorTitle: document.getElementById('error-title'),
    errorMessage: document.getElementById('error-message'),
    empty: document.getElementById('state-empty'),
    emptyReset: document.getElementById('empty-reset-btn'),
    grid: document.getElementById('news-grid'),
    retry: document.getElementById('retry-btn'),
    footerUpdated: document.getElementById('footer-updated'),
    title: document.getElementById('app-title'),
  };

  document.title = els.title.textContent;
  bindEvents();
  boot();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}