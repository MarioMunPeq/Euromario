/**
 * Gaming Digest — Frontend App
 * Vanilla JS: fetch, filters, URL sync, rendering, error handling
 */

// ============================================================
// Configuration
// ============================================================

const CONFIG = {
  appTitle: 'Gaming Digest',
  dataUrl: 'data/news.json',
  cacheBustParam: 'v',
  dateFormat: { year: 'numeric', month: 'short', day: 'numeric' },
  relativeTimeLocale: 'es',
  itemsPerPage: 50,
  debounceMs: 150,
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
  filterGame: document.getElementById('filter-game'),
  filterCategory: document.getElementById('filter-category'),
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

function formatRelativeDate(date, locale = 'es') {
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

  return date.toLocaleDateString('es', { year: 'numeric', month: 'short', day: 'numeric' });
}

function formatDate(date, locale = 'es') {
  return date.toLocaleDateString(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function getRelevanceStars(relevance) {
  const full = '★'.repeat(relevance);
  const empty = '☆'.repeat(5 - relevance);
  return `<span class="news-card__relevance" aria-label="Relevancia: ${relevance}/5">${full}${empty}</span>`;
}

function getCategoryBadge(category) {
  const labels = {
    lanzamiento: 'Lanzamiento',
    actualizacion: 'Actualización',
    rumor: 'Rumor',
    analisis: 'Análisis',
  };
  return `<span class="badge badge--category">${labels[category] || category}</span>`;
}

function getSourceBadge(source) {
  const labels = {
    media: { class: 'badge--media', label: source.name },
    steam: { class: 'badge--steam', label: `Steam · ${source.name}` },
    reddit: { class: 'badge--reddit', label: 'Reddit · no verificado' },
  };
  const config = labels[source.type] || { class: 'badge', label: source.name };
  return `<span class="badge ${config.class}">${config.label}</span>`;
}

function getGameBadge(game) {
  return `<span class="badge badge--category">${escapeHtml(game)}</span>`;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ============================================================
// Reddit SVG Icon (inline, no external deps)
// ============================================================

const REDDIT_SVG = `
<svg class="badge__icon" viewBox="0 0 24 24" width="12" height="12" fill="currentColor" aria-hidden="true">
  <path d="M12 2C6.48 2 2 6.48 2 12c0 5.52 4.48 10 10 10s10-4.48 10-10c0-5.52-4.48-10-10-10zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 11H7v2h2v1.88c-.7.21-1.19.83-1.19 1.64 0 1.06.72 1.87 1.66 1.97.26.03.5-.07.65-.26l1.31-1.5c.72 1.22 2.14 2 3.69 2h1v-2h-1c-.62 0-1.07-.57-1-1.16v-1.24l1.54-.3c.24-.58.95-1.15 1.72-1.15.87 0 1.64.77 1.64 1.83 0 1.14-.72 1.88-1.82 1.83-1.22 0-2.04-.92-1.88-1.92l-1.52-1.42c-.6-.6-.6-1.6 0-2.2l1.33-1.33c-.74-.42-1.32-1.14-1.58-2H10v2h2c.04 2.03 2.65 3.57 4.92 3.5 1.8-.04 3.32-1.15 3.86-2.78.29-.87.14-1.76-.4-2.5l-1.34-1.47c-.3-.3-.3-1.6 0-2.2l1.32-1.32c.73-.75 1.13-1.84 1.13-2.88 0-1.86-1.5-3.2-3.35-2.8-1.3.06-2.52.98-2.88 2.13l-1.51 1.32c-.46.4-.46 1.6 0 2l1.5 1.42c.3.3.3 1.6 0 2.2l-1.32 1.33c-.7.7-1.06 1.73-1.07 2.9 0 1.84 1.5 3.21 3.3 2.86 1.2-.07 2.45-.9 2.78-2.05l1.38-1.31c.43-.4.43-1.6 0-2.2L15.54 6.5c-.67-.67-1.8-1.07-2.9-1.07-.37 0-.73.05-1.06.14l-1.58 1.4c-.6.58-.6 1.6 0 2.2l1.51 1.43c-.3.3-.3.7-.3 1 0 1.3.86 2.44 2.15 2.8.36.1.73.1 1.09.1 2.03 0 3.53-1.76 3.5-3.85-.02-1.02-.64-1.88-1.5-2.38l-1.3-1.4c-.5-.5-.5-1.6 0-2.1l1.4-1.3c.32-.3.32-.75.02-1.07-.28-.3-.72-.38-1.1-.2-.52.18-.85.73-.85 1.35 0 .44.23.87.6 1.1l1.3 1.3c.67.7 1.07 1.8.7 2.9-.1.37-.3.73-.7.99l-1.34 1.3c-.83.84-1.9 1.4-3.1 1.4-.94 0-1.8-.55-2.22-1.33l-1.54-1.42c-.6-.6-.6-1.6 0-2.2l1.35-1.35c.5-.5.5-1.3.02-1.8-.3-.3-.7-.38-1.1-.2-.4.2-.65.68-.82 1.2 0 .35.18.7.5 1.07l1.4 1.3c.6.6 1 .6 1.6.2.2-.14.37-.3.5-.5l1.3-1.4c.6-.6.6-1.6 0-2.2l-1.5-1.4z"/>
</svg>
`;

// ============================================================
// Data Fetching
// ============================================================

async function fetchNews() {
  const url = `${CONFIG.dataUrl}?${CONFIG.cacheBustParam}=${Date.now()}`;
  console.log('[DEBUG] fetchNews: START', { url: url, dataUrl: CONFIG.dataUrl, cacheBustParam: CONFIG.cacheBustParam });
  try {
    const response = await fetch(url, {
      cache: 'no-store',
      headers: { 'Accept': 'application/json' },
    });
    console.log('[DEBUG] fetchNews: response received', { status: response.status, ok: response.ok, url: response.url });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    console.log('[DEBUG] fetchNews: JSON parsed', { hasData: !!data, hasNews: Array.isArray(data?.news), newsLength: data?.news?.length, keys: data ? Object.keys(data) : 'no data' });

    // Validate structure
    if (!data || !Array.isArray(data.news)) {
      throw new Error('Formato de datos inválido');
    }

    console.log('[app] fetchNews: parsed', data.news.length, 'news items');
    return data;
  } catch (err) {
    console.error('[ERROR] fetchNews failed:', err);
    throw err;
  }
}

// ============================================================
// Rendering
// ============================================================

function renderNewsCard(item) {
  const gameBadge = item.game ? getGameBadge(item.game) : '';
  const categoryBadge = item.category ? getCategoryBadge(item.category) : '';
  const sourceBadge = getSourceBadge(item.source);
  const relevanceStars = getRelevanceStars(item.relevance);
  const dateStr = formatRelativeDate(new Date(item.published_at));
  const publishedDate = formatDate(new Date(item.published_at));

  return `
    <article class="news-card" data-id="${item.id}">
      <header class="news-card__header">
        <div class="news-card__source">
          ${getSourceBadge(item.source)}
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
          ${item.category ? getCategoryBadge(item.category) : ''}
        </div>
        <span class="news-card__relevance" aria-label="Relevancia: ${item.relevance}/5">
          ${'★'.repeat(item.relevance)}${'☆'.repeat(5 - item.relevance)}
        </span>
        <time class="news-card__date" datetime="${new Date(item.published_at).toISOString()}">
          ${formatRelativeDate(new Date(item.published_at))}
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
  const generatedAt = data.generated_at ? new Date(data.generated_at) : new Date();
  const countStr = count.toLocaleString('es');
  const updatedStr = `Actualizado: ${formatDate(new Date(data.generated_at))} ${formatRelativeDate(new Date(data.generated_at))}`;

  // Update footer stats
  if (els.statsCount) els.statsCount.textContent = countStr;
  if (els.statsUpdated) els.statsUpdated.textContent = updatedStr;

  // Update header meta
  if (els.headerCount) els.headerCount.textContent = `${countStr} noticias`;
  if (els.headerUpdated) {
    els.headerUpdated.textContent = `Actualizado ${formatRelativeDate(new Date(data.generated_at))}`;
    els.headerUpdated.dateTime = new Date(data.generated_at).toISOString();
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
  console.log('[DEBUG] setState:', stateName);
  // Hide all states
  console.log('[DEBUG] setState: hiding all states');
  els.stateLoading.hidden = true;
  els.stateError.hidden = true;
  els.stateEmpty.hidden = true;
  els.newsList.hidden = true;
  
  // Show requested state
  const stateEl = document.getElementById(`state-${stateName}`);
  if (stateEl) {
    console.log('[DEBUG] setState: showing state element', stateName);
    stateEl.hidden = false;
  } else if (stateName === 'content') {
    console.log('[DEBUG] setState: showing content (news-list)');
    els.newsList.hidden = false;
  } else {
    console.warn('[WARN] setState: unknown state', stateName);
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
  els.stateError.querySelector('#error-title').textContent = title;
  els.errorMessage.textContent = message;
  setState('error');
}

function clearError() {
  state.ui.error = null;
}

function showEmpty() {
  setState('empty');
}

// ============================================================
// Filtering
// ============================================================

function applyFilters() {
  const { games, categories, dateFrom, dateTo, search } = state.filters;

  state.filteredNews = state.allNews.filter(item => {
    // Search
    if (search) {
      const query = search.toLowerCase();
      const haystack = `${item.title} ${item.summary || ''} ${item.game || ''}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }

    // Game filter (OR)
    if (state.filters.games.length > 0) {
      if (!item.game || !state.filters.games.includes(item.game)) return false;
    }

    // Category filter (OR)
    if (state.filters.categories.length > 0) {
      if (!item.category || !state.filters.categories.includes(item.category)) return false;
    }

    // Date range
    const itemDate = new Date(item.published_at);
    if (state.filters.dateFrom && itemDate < new Date(state.filters.dateFrom)) return false;
    if (state.filters.dateTo) {
      const toDate = new Date(state.filters.dateTo);
      toDate.setHours(23, 59, 59, 999);
      if (itemDate > toDate) return false;
    }

    return true;
  });

  renderNewsList(state.filteredNews);
  
  // Update footer stats (only count, not the full renderStats)
  if (els.statsCount) els.statsCount.textContent = state.filteredNews.length.toLocaleString('es');
}

function populateGameFilter(items) {
  const games = [...new Set(items.map(i => i.game).filter(Boolean))].sort();
  els.filterGame.innerHTML = '<option value="">Todos los juegos</option>' +
    games.map(g => `<option value="${escapeHtml(g)}">${escapeHtml(g)}</option>`).join('');
}

function updateFilterUI() {
  // Sync select values
  Array.from(els.filterGame.options).forEach(opt => {
    opt.selected = state.filters.games.includes(opt.value);
  });
  Array.from(els.filterCategory.options).forEach(opt => {
    opt.selected = state.filters.categories.includes(opt.value);
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
  state.filters.games = Array.from(els.filterGame.selectedOptions).map(o => o.value).filter(Boolean);
  state.filters.categories = Array.from(els.filterCategory.selectedOptions).map(o => o.value).filter(Boolean);
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
  updateFilterUI();
  applyFilters();
  pushUrl();
}

function onRetry() {
  clearError();
  loadData();
}

// ============================================================
// Data Loading
// ============================================================

async function loadData() {
  console.log('[DEBUG] loadData: START');
  setLoading(true);
  clearError();

  try {
    console.log('[DEBUG] loadData: calling fetchNews');
    const data = await fetchNews();
    console.log('[DEBUG] loadData: fetchNews returned', { newsLength: data.news.length, total: data.total, generated_at: data.generated_at });
    state.allNews = data.news;
    state.filteredNews = data.news;

    // Populate game filter from all news
    populateGameFilter(data.news);

    // Apply any URL-synced filters
    syncUrlToState();
    updateFilterUI();
    applyFilters();

    // Render
    renderNewsList(state.filteredNews);
    renderStats(data);
    setAppTitle();
    console.log('[DEBUG] loadData: COMPLETE, filteredNews=', state.filteredNews.length);
  } catch (err) {
    console.error('[ERROR] loadData failed:', err);
    setError(
      err.message.includes('404') || err.message.includes('Failed to fetch')
        ? 'No se encontraron noticias (primera ejecución pendiente).'
        : `Error de red: ${err.message}`,
      'No se pudieron cargar las noticias'
    );
    // No finally block that overrides error state
    return;
  }

  // Only set to content state on success
  setLoading(false);
}

// ============================================================
// Initialization
// ============================================================

function init() {
  console.log('[DEBUG] init: START');
  setAppTitle();

  // Event listeners
  const debouncedFilterChange = debounce(onFilterChange, CONFIG.debounceMs);

  els.search.addEventListener('input', debouncedFilterChange);
  els.filterGame.addEventListener('change', onFilterChange);
  els.filterCategory.addEventListener('change', onFilterChange);
  els.dateFrom.addEventListener('change', onFilterChange);
  els.dateTo.addEventListener('change', onFilterChange);
  els.clearFilters.addEventListener('click', onClearFilters);
  els.retryBtn.addEventListener('click', onRetry);

  // URL sync on popstate
  window.addEventListener('popstate', () => {
    syncUrlToState();
    updateFilterUI();
    applyFilters();
  });

  // Initial load
  console.log('[DEBUG] init: calling loadData');
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