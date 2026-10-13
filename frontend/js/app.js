/**
 * EuroMario — Frontend App
 * Vanilla JS: fetch, filters, URL sync, rendering, error handling
 * Gaming Pulse editorial card design with cover images
 */

// ============================================================
// Configuration
// ============================================================

const CONFIG = {
  appTitle: 'EuroMario',
  dataUrl: 'data/news.json',
  gamesUrl: 'data/games.json',
  cacheBustParam: 'v',
  itemsPerPage: 50,
};

const CATEGORY_LABELS = {
  lanzamiento: 'Release',
  actualizacion: 'Update',
  rumor: 'Rumor',
  analisis: 'Analysis',
};



const CATEGORY_COLORS = {
  lanzamiento: 'var(--cat-lanzamiento)',
  actualizacion: 'var(--cat-actualizacion)',
  rumor: 'var(--cat-rumor)',
  analisis: 'var(--cat-analisis)',
};

// ============================================================
// State
// ============================================================

const state = {
  allNews: [],
  filteredNews: [],
  gameLogos: {},
  filters: {
    game: null,
    section: 'news',
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
  stateLoading: document.getElementById('state-loading'),
  stateError: document.getElementById('state-error'),
  stateEmpty: document.getElementById('state-empty'),
  errorTitle: document.getElementById('error-title'),
  errorMessage: document.getElementById('error-message'),
  newsList: document.getElementById('news-list'),
  retryBtn: document.getElementById('retry-btn'),
  clearFiltersBtn: document.getElementById('clear-filters-btn'),
  headerGameFiltersDesktop: document.getElementById('header-game-filters-desktop'),
  headerGameFiltersMobile: document.getElementById('header-game-filters-mobile'),
  headerNavButtons: document.querySelectorAll('.header__nav-btn'),
};

// ============================================================
// Utilities
// ============================================================

function formatDate(date) {
  return date.toLocaleDateString('en', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function getGameInitial(name) {
  return name.charAt(0).toUpperCase();
}


function getSourceInitials(name) {
  if (!name) return '?';
  const cleaned = name.replace(/\s*\u00b7\s*.+$/, '').trim();
  const words = cleaned.split(/\s+/);
  if (words.length === 1) return words[0].substring(0, 3).toUpperCase();
  if (words.length === 2) return (words[0][0] + words[1][0]).toUpperCase();
  return words.slice(0, 3).map(w => w[0]).join('').toUpperCase();
}

function getCategoryColor(category) {
  return CATEGORY_COLORS[category] || 'var(--accent)';
}

// ============================================================
// Source Helpers (soporta ambos formatos: plano y anidado)
// ============================================================

function getSourceName(source, sourceType) {
  // source puede ser string (formato nuevo) u objeto {name, type, subreddit} (formato histórico)
  const name = typeof source === 'string' ? source : (source?.name ?? 'Unknown');
  if (sourceType === 'reddit') return 'Reddit';
  return name;
}

function getSourceType(item) {
  // source_type puede venir como campo plano (formato nuevo) o dentro de source (formato histórico)
  return item.source_type ?? item.source?.type ?? 'media';
}

function getSourceSubreddit(item) {
  return item.source?.subreddit ?? null;
}

// ============================================================
// Game Tiles (visual filter with logo support)
// ============================================================

const DARK_BG_SVGS = new Set([
  'baldurs-gate', 'call-of-duty', 'cyberpunk', 'elden-ring', 'final-fantasy',
  'god-of-war', 'helldivers', 'hollow-knight', 'minecraft', 'persona', 'pokemon',
  'pubg', 'rainbow-six', 'roblox', 'starfield', 'super-mario', 'zelda',
]);

const TILES_MOBILE_MQL = window.matchMedia('(max-width: 768px)');

// Juegos prioritarios para header filters
const PRIORITY_GAMES = ['Grand Theft Auto', 'Pokemon'];

function renderAllTiles(newsItems, games) {
  // Render header game filters (desktop + mobile) - just GTA and Pokemon
  const priorityGames = PRIORITY_GAMES.filter(g => games.includes(g));
  const createHeaderTile = (game, size) => {
    const logo = state.gameLogos[game];
    const label = game === 'Grand Theft Auto' ? 'GTA' : escapeHtml(game);
    if (logo) {
      return `
        <button type="button" class="header__game-filter" data-game="${escapeHtml(game)}" aria-pressed="false" aria-label="${label}">
          <img class="header__game-filter-icon" src="${escapeHtml(logo)}" alt="" aria-hidden="true" width="${size}" height="${size}">
        </button>`;
    }
    return `
      <button type="button" class="header__game-filter" data-game="${escapeHtml(game)}" aria-pressed="false" aria-label="${label}">
        <span class="header__game-filter-icon">${getGameInitial(game)}</span>
      </button>`;
  };

  // Desktop: 48px icons
  if (els.headerGameFiltersDesktop) {
    els.headerGameFiltersDesktop.innerHTML = priorityGames.map(g => createHeaderTile(g, 48)).join('');
  }

  // Mobile: 32px icons
  if (els.headerGameFiltersMobile) {
    els.headerGameFiltersMobile.innerHTML = priorityGames.map(g => createHeaderTile(g, 32)).join('');
  }

  // Show/hide based on screen size
  const isMobile = TILES_MOBILE_MQL.matches;
  if (els.headerGameFiltersDesktop) {
    els.headerGameFiltersDesktop.hidden = isMobile;
  }
  if (els.headerGameFiltersMobile) {
    els.headerGameFiltersMobile.hidden = !isMobile;
  }

  // Attach game handlers to header filters (desktop + mobile)
  if (els.headerGameFiltersDesktop) {
    attachGameHandlers(els.headerGameFiltersDesktop);
  }
  if (els.headerGameFiltersMobile) {
    attachGameHandlers(els.headerGameFiltersMobile);
  }
}

const attachGameHandlers = (container) => {
  // Simple click on header__game-filter (both desktop and mobile)
  container.querySelectorAll('.header__game-filter').forEach(tile => {
    tile.addEventListener('click', () => {
      const game = tile.dataset.game;
      const wasActive = tile.getAttribute('aria-pressed') === 'true';

      // Update both filter areas
      document.querySelectorAll('.header__game-filter, [data-game]').forEach(t => {
        t.classList.remove('active');
        t.setAttribute('aria-pressed', 'false');
      });

      if (wasActive) {
        state.filters.game = null;
      } else {
        state.filters.game = game;
      }
      applyFilters();
      pushUrl();
      syncFilterUIFromState();
    });
  });
};

// ============================================================
// Header Section Navigation (NEWS / RUMORS)
// ============================================================

function initHeaderNav() {
  els.headerNavButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const section = btn.dataset.section;
      const wasActive = btn.getAttribute('aria-checked') === 'true';

      els.headerNavButtons.forEach(b => {
        b.setAttribute('aria-checked', 'false');
      });

      if (wasActive) {
        state.filters.section = null;
      } else {
        state.filters.section = section;
        btn.setAttribute('aria-checked', 'true');
      }
      applyFilters();
      pushUrl();
    });
  });
}

// ============================================================
// Rendering — Gaming Pulse Card Design
// ============================================================

function getAvatarColor(sourceType) {
  if (sourceType === 'reddit') return 'var(--reddit, #FF4500)';
  if (sourceType === 'steam') return 'var(--steam, #66C0F4)';
  return 'var(--surface-elevated)';
}

// Text inside the avatar circle. Steam blue is light: #fff sobre #66C0F4 es 2.02:1
// (falla AA); navy alcanza 9.17:1. Reddit naranja con letras blancas es su identidad
// y pasa AA large-text (3.44:1).
function getAvatarTextColor(sourceType) {
  if (sourceType === 'steam') return 'var(--bg)';
  return '#fff';
}

function renderNewsCard(item) {
  const category = item.category || '';
  const catColor = getCategoryColor(category);
  const sourceType = getSourceType(item);
  const sourceName = getSourceName(item.source, sourceType);
  const gameName = item.game || sourceName;
  const isHighRelevance = item.relevance >= 4;

  const sectionLabel = category === 'rumor' ? 'RUMOR' : 'NEWS';
  const isReddit = sourceType === 'reddit';

  const overlayHtml = `
      <div class="news-card__overlay news-card__overlay--placeholder">
        <div class="news-card__overlay-content">
          <span class="news-card__section">${sectionLabel}</span>
          <span class="news-card__game">${escapeHtml(gameName.toUpperCase())}</span>
        </div>
      </div>`;

  let mediaHtml;
  if (isReddit) {
    mediaHtml = `
      <div class="news-card__placeholder news-card__placeholder--reddit" role="img" aria-label="Reddit">
        <img src="assets/icons/reddit.svg" alt="" class="news-card__placeholder-logo"/>
      </div>
      ${overlayHtml}`;
  } else if (item.image) {
    mediaHtml = `
      <img src="${escapeHtml(item.image)}" alt="" class="news-card__image" loading="lazy"/>
      ${overlayHtml}`;
  } else {
    mediaHtml = `
      <div class="news-card__placeholder" style="--cat-color: ${catColor}">
        <span class="news-card__placeholder-initials">${escapeHtml(getSourceInitials(getSourceName(item.source, sourceType)))}</span>
      </div>
      ${overlayHtml}`;
  }

  const dateObj = new Date(item.published_at);
  const dateStr = formatDate(dateObj);
  const sourceLabel = escapeHtml(sourceName.toUpperCase());
  const metaLine = `${sourceLabel} · ${dateStr}`;

  return `
    <article class="news-card${isHighRelevance ? ' news-card--high' : ''}" data-id="${item.id}" data-category="${category}" style="--cat-color: ${catColor}">
      <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" class="news-card__media-link">
        <div class="news-card__media">
          ${mediaHtml}
        </div>
      </a>
      <div class="news-card__content">
        <div class="news-card__meta">
          <time class="news-card__date" datetime="${dateObj.toISOString()}">${metaLine}</time>
        </div>
        <h3 class="news-card__title">
          <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">
            ${escapeHtml(item.title)}
          </a>
        </h3>
${item.summary ? `<p class="news-card__summary">${escapeHtml(item.summary)}</p>` : ''}
      </div>
    </article>`;
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
    if (stateName === 'empty') {
      els.clearFiltersBtn.hidden = !hasActiveFilters();
    }
  } else if (stateName === 'content') {
    els.newsList.hidden = false;
  }
}

function hasActiveFilters() {
  return Boolean(
    state.filters.game ||
    state.filters.section
  );
}

function resetFilters() {
  state.filters.game = null;
  state.filters.section = null;
  syncFilterUIFromState();
  applyFilters();
  pushUrl();
}

function setLoading(loading) {
  state.ui.loading = loading;
  if (loading) {
    setState('loading');
  } else {
    setState('content');
  }
}

function setError(message, title = 'Failed to load') {
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
  const { game, section } = state.filters;

  state.filteredNews = state.allNews.filter(item => {
    if (game) {
      if (!item.game || item.game !== game) return false;
    }

    // Section filter: NEWS = all except rumor, RUMORS = only rumor
    if (section === 'news') {
      if (item.category === 'rumor') return false;
    } else if (section === 'rumors') {
      if (item.category !== 'rumor') return false;
    }

    return true;
  });

  renderNewsList(state.filteredNews);
}

function syncFilterUIFromState() {
  const currentGame = state.filters.game || '';

  // Sync mobile carousel and header game filters
  document.querySelectorAll('[data-game], [data-game-clone], .header__game-filter').forEach(tile => {
    const game = tile.dataset.game || tile.dataset.gameClone || '';
    const isActive = game === currentGame;
    tile.classList.toggle('active', isActive);
    tile.setAttribute('aria-pressed', String(isActive));
  });

  els.headerNavButtons.forEach(btn => {
    const section = btn.dataset.section;
    const isActive = state.filters.section === section;
    btn.setAttribute('aria-checked', String(isActive));
  });
}

// ============================================================
// URL Synchronization
// ============================================================

function filtersToUrlParams() {
  const params = new URLSearchParams();
  if (state.filters.game) params.set('game', state.filters.game);
  if (state.filters.section) params.set('section', state.filters.section);
  return params.toString();
}

function syncUrlToState() {
  const params = new URLSearchParams(window.location.search);
  state.filters.game = params.get('game') || null;
  state.filters.section = params.get('section') || null;
}

function pushUrl() {
  const params = filtersToUrlParams();
  const url = params.toString() ? `?${params.toString()}` : window.location.pathname;
  history.replaceState(null, '', url);
}

// ============================================================
// Event Handlers
// ============================================================

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

async function fetchGameData() {
  const url = `${CONFIG.gamesUrl}?${CONFIG.cacheBustParam}=${Date.now()}`;
  try {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) return { logos: {}, platforms: {}, names: new Set() };
    const data = await response.json();
    if (!data || !Array.isArray(data.games)) return { logos: {}, platforms: {}, names: new Set() };
    const logos = {};
    const platforms = {};
    const names = new Set();
    for (const g of data.games) {
      if (g.name) {
        names.add(g.name);
        if (g.logo) logos[g.name] = `assets/games/${g.logo}`;
        if (Array.isArray(g.platform)) platforms[g.name] = g.platform;
      }
    }
    return { logos, platforms, names };
  } catch {
    return { logos: {}, platforms: {}, names: new Set() };
  }
}

// ============================================================
// Data Loading
// ============================================================

async function loadData() {
  setLoading(true);
  clearError();

  try {
    const [data, gameData] = await Promise.all([fetchNews(), fetchGameData()]);
    state.allNews = data.news;
    state.filteredNews = data.news;
    state.gameLogos = gameData.logos;

    const configNames = gameData.names || new Set();
    const games = [...configNames].sort();
    renderAllTiles(data.news, games);
    initHeaderNav();

    syncUrlToState();
    syncFilterUIFromState();
    applyFilters();
    setAppTitle();
  } catch (err) {
    setError(
      err.message.includes('404') || err.message.includes('Failed to fetch')
        ? 'No news found (first run pending).'
        : `Network error: ${err.message}`,
      'Failed to load news'
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

  els.retryBtn.addEventListener('click', onRetry);
  els.clearFiltersBtn.addEventListener('click', resetFilters);

  window.addEventListener('popstate', () => {
    syncUrlToState();
    syncFilterUIFromState();
    applyFilters();
  });

  loadData();
}

function getSectionName(section) {
  return section === 'news' ? 'NEWS' : 'RUMORS';
}

// ============================================================
// Boot
// ============================================================

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
