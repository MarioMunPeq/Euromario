/**
 * EuroMario — Frontend App
 * Vanilla JS: fetch, filters, URL sync, rendering, error handling
 */

// ============================================================
// Configuration
// ============================================================

const CONFIG = {
  appTitle: 'EuroMario',
  dataUrl: 'data/news.json',
  cacheBustParam: 'v',
  itemsPerPage: 50,
  debounceMs: 150,
};

const CATEGORY_LABELS = {
  lanzamiento: 'Lanzamiento',
  actualizacion: 'Actualizaci\u00f3n',
  rumor: 'Rumor',
  analisis: 'An\u00e1lisis',
};

// ============================================================
// State
// ============================================================

const state = {
  allNews: [],
  filteredNews: [],
  filters: {
    games: [],
    categories: [],
    dateFrom: null,
    dateTo: null,
    search: '',
  },
  ui: {
    loading: false,
    error: null,
  },
};

// ============================================================
// DOM Elements
// ============================================================

const els = {
  title: document.getElementById('app-title'),
  headerCount: document.getElementById('header-count'),
  headerUpdated: document.getElementById('header-updated'),
  stateLoading: document.getElementById('state-loading'),
  stateError: document.getElementById('state-error'),
  stateEmpty: document.getElementById('state-empty'),
  errorTitle: document.getElementById('error-title'),
  errorMessage: document.getElementById('error-message'),
  newsList: document.getElementById('news-list'),
  retryBtn: document.getElementById('retry-btn'),
  search: document.getElementById('search'),
  gameTiles: document.getElementById('game-tiles'),
  categoryPills: document.getElementById('category-pills'),
  dateFrom: document.getElementById('date-from'),
  dateTo: document.getElementById('date-to'),
  clearFilters: document.getElementById('clear-filters'),
  statsCount: document.getElementById('stats-count'),
  statsUpdated: document.getElementById('stats-updated'),
};

// ============================================================
// Utilities
// ============================================================

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function formatDate(date) {
  return date.toLocaleDateString('es', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function formatRelativeDate(date) {
  const now = new Date();
  const diffMs = now - date;
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffSec < 60) return 'ahora mismo';
  if (diffMin < 60) return `hace ${diffMin} min`;
  if (diffHour < 24) return `hace ${diffHour}h`;
  if (diffDay < 30) return `hace ${diffDay}d`;
  return formatDate(date);
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function getGameInitial(name) {
  return name.charAt(0).toUpperCase();
}

// ============================================================
// Source Badge
// ============================================================

function getSourceBadge(source) {
  const labels = {
    media: { class: 'badge--media', label: source.name },
    steam: { class: 'badge--steam', label: source.name },
    reddit: { class: 'badge--reddit', label: 'Reddit' },
  };
  const config = labels[source.type] || { class: 'badge', label: source.name };
  return `<span class="badge ${config.class}">${escapeHtml(config.label)}</span>`;
}

function getCategoryBadge(category) {
  return `<span class="badge badge--category">${CATEGORY_LABELS[category] || category}</span>`;
}

// ============================================================
// Game Tiles (visual filter)
// ============================================================

function renderGameTiles(games) {
  const allTile = `
    <button type="button" class="game-tile active" data-game="" aria-pressed="true">
      <div class="game-tile__icon">ALL</div>
      <span class="game-tile__name">Todos</span>
    </button>`;

  const gameTiles = games.map(game => `
    <button type="button" class="game-tile" data-game="${escapeHtml(game)}" aria-pressed="false">
      <div class="game-tile__icon">${getGameInitial(game)}</div>
      <span class="game-tile__name">${escapeHtml(game)}</span>
    </button>`).join('');

  els.gameTiles.innerHTML = allTile + gameTiles;

  els.gameTiles.querySelectorAll('.game-tile').forEach(tile => {
    tile.addEventListener('click', () => {
      const game = tile.dataset.game;
      if (game === '') {
        state.filters.games = [];
        els.gameTiles.querySelectorAll('.game-tile').forEach(t => {
          t.classList.remove('active');
          t.setAttribute('aria-pressed', 'false');
        });
        tile.classList.add('active');
        tile.setAttribute('aria-pressed', 'true');
      } else {
        const allBtn = els.gameTiles.querySelector('[data-game=""]');
        allBtn.classList.remove('active');
        allBtn.setAttribute('aria-pressed', 'false');

        if (state.filters.games.includes(game)) {
          state.filters.games = state.filters.games.filter(g => g !== game);
          tile.classList.remove('active');
          tile.setAttribute('aria-pressed', 'false');
          if (state.filters.games.length === 0) {
            allBtn.classList.add('active');
            allBtn.setAttribute('aria-pressed', 'true');
          }
        } else {
          state.filters.games.push(game);
          tile.classList.add('active');
          tile.setAttribute('aria-pressed', 'true');
        }
      }
      applyFilters();
      pushUrl();
    });
  });
}

// ============================================================
// Category Pills
// ============================================================

function initCategoryPills() {
  els.categoryPills.querySelectorAll('.category-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      const cat = pill.dataset.cat;
      if (state.filters.categories.includes(cat)) {
        state.filters.categories = state.filters.categories.filter(c => c !== cat);
        pill.classList.remove('active');
      } else {
        state.filters.categories.push(cat);
        pill.classList.add('active');
      }
      applyFilters();
      pushUrl();
    });
  });
}

// ============================================================
// Rendering
// ============================================================

function renderNewsCard(item) {
  const categoryBadge = item.category ? getCategoryBadge(item.category) : '';
  const sourceBadge = getSourceBadge(item.source);
  const dateObj = new Date(item.published_at);
  const dateStr = formatDate(dateObj);
  const relStr = formatRelativeDate(dateObj);

  return `
    <article class="news-card" data-id="${item.id}" data-category="${item.category || ''}">
      <header class="news-card__header">
        <div class="news-card__source">
          ${sourceBadge}
        </div>
        <div class="news-card__title">
          <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">
            ${escapeHtml(item.title)}
          </a>
        </div>
      </header>
      ${item.summary ? `<p class="news-card__summary">${escapeHtml(item.summary)}</p>` : ''}
      <footer class="news-card__meta">
        <div class="news-card__badges">
          ${item.game ? `<span class="badge badge--category">${escapeHtml(item.game)}</span>` : ''}
          ${categoryBadge}
        </div>
        <span class="news-card__relevance" aria-label="Relevancia: ${item.relevance}/5">
          ${'\u2605'.repeat(item.relevance)}${'\u2606'.repeat(5 - item.relevance)}
        </span>
        <time class="news-card__date" datetime="${dateObj.toISOString()}" title="${relStr}">
          ${dateStr}
        </time>
      </footer>
    </article>
  `;
}

function renderNewsList(items) {
  if (!items.length) {
    els.newsList.innerHTML = '';
    setState('empty');
    return;
  }

  els.newsList.innerHTML = items.map(renderNewsCard).join('');
  setState('content');
}

function renderStats(data) {
  const count = data.total ?? data.news?.length ?? 0;
  const countStr = count.toLocaleString('es');
  const updatedStr = data.generated_at
    ? formatDate(new Date(data.generated_at))
    : '\u2014';

  if (els.statsCount) els.statsCount.textContent = countStr;
  if (els.statsUpdated) els.statsUpdated.textContent = updatedStr;

  if (els.headerCount) els.headerCount.textContent = `${countStr} noticias`;
  if (els.headerUpdated) {
    els.headerUpdated.textContent = data.generated_at
      ? `Actualizado ${formatRelativeDate(new Date(data.generated_at))}`
      : '\u2014';
    els.headerUpdated.dateTime = data.generated_at
      ? new Date(data.generated_at).toISOString()
      : '';
  }
}

function setAppTitle() {
  if (els.title) {
    els.title.textContent = CONFIG.appTitle;
    document.title = CONFIG.appTitle;
  }
}

// ============================================================
// State Management
// ============================================================

function setState(stateName) {
  els.stateLoading.hidden = true;
  els.stateError.hidden = true;
  els.stateEmpty.hidden = true;
  els.newsList.hidden = true;

  const stateEl = document.getElementById(`state-${stateName}`);
  if (stateEl) {
    stateEl.hidden = false;
  } else if (stateName === 'content') {
    els.newsList.hidden = false;
  }
}

function setLoading(loading) {
  state.ui.loading = loading;
  if (loading) {
    setState('loading');
  } else {
    setState('content');
  }
}

function setError(message, title = 'Error al cargar') {
  state.ui.error = message;
  state.ui.loading = false;
  els.errorTitle.textContent = title;
  els.errorMessage.textContent = message;
  setState('error');
}

function clearError() {
  state.ui.error = null;
}

// ============================================================
// Filtering
// ============================================================

function applyFilters() {
  const { games, categories, dateFrom, dateTo, search } = state.filters;

  state.filteredNews = state.allNews.filter(item => {
    if (search) {
      const query = search.toLowerCase();
      const haystack = `${item.title} ${item.summary || ''} ${item.game || ''}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }

    if (games.length > 0) {
      if (!item.game || !games.includes(item.game)) return false;
    }

    if (categories.length > 0) {
      if (!item.category || !categories.includes(item.category)) return false;
    }

    const itemDate = new Date(item.published_at);
    if (dateFrom && itemDate < new Date(dateFrom)) return false;
    if (dateTo) {
      const toDate = new Date(dateTo);
      toDate.setHours(23, 59, 59, 999);
      if (itemDate > toDate) return false;
    }

    return true;
  });

  renderNewsList(state.filteredNews);
  if (els.statsCount) els.statsCount.textContent = state.filteredNews.length.toLocaleString('es');
}

function syncFilterUIFromState() {
  els.gameTiles.querySelectorAll('.game-tile').forEach(tile => {
    const game = tile.dataset.game;
    const isActive = game === '' ? state.filters.games.length === 0 : state.filters.games.includes(game);
    tile.classList.toggle('active', isActive);
    tile.setAttribute('aria-pressed', String(isActive));
  });

  els.categoryPills.querySelectorAll('.category-pill').forEach(pill => {
    const cat = pill.dataset.cat;
    pill.classList.toggle('active', state.filters.categories.includes(cat));
  });

  els.dateFrom.value = state.filters.dateFrom || '';
  els.dateTo.value = state.filters.dateTo || '';
  els.search.value = state.filters.search || '';
}

// ============================================================
// URL Synchronization
// ============================================================

function filtersToUrlParams() {
  const params = new URLSearchParams();
  if (state.filters.games.length) params.set('game', state.filters.games.join(','));
  if (state.filters.categories.length) params.set('category', state.filters.categories.join(','));
  if (state.filters.dateFrom) params.set('date_from', state.filters.dateFrom);
  if (state.filters.dateTo) params.set('date_to', state.filters.dateTo);
  if (state.filters.search) params.set('q', state.filters.search);
  return params.toString();
}

function syncUrlToState() {
  const params = new URLSearchParams(window.location.search);
  state.filters.games = params.get('game')?.split(',').filter(Boolean) || [];
  state.filters.categories = params.get('category')?.split(',').filter(Boolean) || [];
  state.filters.dateFrom = params.get('date_from') || null;
  state.filters.dateTo = params.get('date_to') || null;
  state.filters.search = params.get('q') || '';
}

function pushUrl() {
  const params = filtersToUrlParams();
  const url = params.toString() ? `?${params.toString()}` : window.location.pathname;
  history.replaceState(null, '', url);
}

// ============================================================
// Event Handlers
// ============================================================

function onFilterChange() {
  state.filters.dateFrom = els.dateFrom.value || null;
  state.filters.dateTo = els.dateTo.value || null;
  state.filters.search = els.search.value.trim();

  applyFilters();
  pushUrl();
}

function onClearFilters() {
  state.filters = {
    games: [],
    categories: [],
    dateFrom: null,
    dateTo: null,
    search: '',
  };
  syncFilterUIFromState();
  applyFilters();
  pushUrl();
}

function onRetry() {
  clearError();
  loadData();
}

// ============================================================
// Data Fetching
// ============================================================

async function fetchNews() {
  const url = `${CONFIG.dataUrl}?${CONFIG.cacheBustParam}=${Date.now()}`;
  try {
    const response = await fetch(url, {
      cache: 'no-store',
      headers: { 'Accept': 'application/json' },
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    if (!data || !Array.isArray(data.news)) {
      throw new Error('Formato de datos inv\u00e1lido');
    }

    return data;
  } catch (err) {
    throw err;
  }
}

// ============================================================
// Data Loading
// ============================================================

async function loadData() {
  setLoading(true);
  clearError();

  try {
    const data = await fetchNews();
    state.allNews = data.news;
    state.filteredNews = data.news;

    const games = [...new Set(data.news.map(i => i.game).filter(Boolean))].sort();
    renderGameTiles(games);
    initCategoryPills();

    syncUrlToState();
    syncFilterUIFromState();
    applyFilters();
    renderStats(data);
    setAppTitle();
  } catch (err) {
    setError(
      err.message.includes('404') || err.message.includes('Failed to fetch')
        ? 'No se encontraron noticias (primera ejecuci\u00f3n pendiente).'
        : `Error de red: ${err.message}`,
      'No se pudieron cargar las noticias'
    );
    return;
  }

  setState(state.filteredNews.length > 0 ? 'content' : 'empty');
}

// ============================================================
// Initialization
// ============================================================

function init() {
  setAppTitle();

  const debouncedFilterChange = debounce(onFilterChange, CONFIG.debounceMs);

  els.search.addEventListener('input', debouncedFilterChange);
  els.dateFrom.addEventListener('change', onFilterChange);
  els.dateTo.addEventListener('change', onFilterChange);
  els.clearFilters.addEventListener('click', onClearFilters);
  els.retryBtn.addEventListener('click', onRetry);

  window.addEventListener('popstate', () => {
    syncUrlToState();
    syncFilterUIFromState();
    applyFilters();
  });

  loadData();
}

// ============================================================
// Boot
// ============================================================

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
