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
  debounceMs: 150,
};

const CATEGORY_LABELS = {
  lanzamiento: 'Lanzamiento',
  actualizacion: 'Actualizaci\u00f3n',
  rumor: 'Rumor',
  analisis: 'An\u00e1lisis',
};

const CATEGORY_GLYPHS = {
  lanzamiento: '\ud83d\ude80',
  actualizacion: '\ud83d\udd04',
  rumor: '\ud83d\udcac',
  analisis: '\ud83d\udcca',
};

const CATEGORY_COLORS = {
  lanzamiento: 'var(--cat-lanzamiento)',
  actualizacion: 'var(--cat-actualizacion)',
  rumor: 'var(--cat-rumor)',
  analisis: 'var(--cat-analisis)',
};

const TILE_COLORS = [
  '#3FB950', '#0080D6', '#D29922', '#A371F7',
  '#F97583', '#56D4DD', '#DB6D28', '#79C0FF',
  '#7EE787', '#D2A8FF', '#FFA657', '#FF7B72',
];

const PLATFORM_ICONS = {
  pc: 'assets/platforms/steam.svg',
  playstation: 'assets/platforms/playstation.svg',
  xbox: 'assets/platforms/xbox.svg',
  nintendo: 'assets/platforms/nintendo.svg',
};

const PLATFORM_LABELS = {
  pc: 'PC',
  playstation: 'PlayStation',
  xbox: 'Xbox',
  nintendo: 'Nintendo',
};

// ============================================================
// State
// ============================================================

const state = {
  allNews: [],
  filteredNews: [],
  gameLogos: {},
  gamePlatforms: {},
  platformGames: {},
  filters: {
    games: [],
    platforms: [],
    categories: [],
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
  platformTiles: document.getElementById('platform-tiles'),
  platformSection: document.getElementById('platform-section'),
  categoryPills: document.getElementById('category-pills'),
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

function hashGameName(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) - hash + name.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % TILE_COLORS.length;
}

function getGameColor(name) {
  return TILE_COLORS[hashGameName(name)];
}

function getCategoryGlyph(category) {
  return CATEGORY_GLYPHS[category] || '\ud83c\udfae';
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

// ============================================================
// Game Tiles (visual filter with logo support)
// ============================================================

const DARK_BG_SVGS = new Set([
  'baldurs-gate', 'call-of-duty', 'elden-ring', 'god-of-war',
  'hollow-knight', 'minecraft', 'persona', 'pokemon',
  'super-mario', 'zelda',
]);

function renderGameTiles(games) {
  const allTile = `
    <button type="button" class="game-tile active" data-game="" aria-pressed="true">
      <div class="game-tile__icon" style="background: var(--accent); border-color: var(--accent)">ALL</div>
      <span class="game-tile__name">Todos</span>
    </button>`;

  const gameTiles = games.map(game => {
    const logo = state.gameLogos[game];
    const color = getGameColor(game);
    if (logo) {
      const slug = logo.split('/').pop().replace('.svg', '');
      const darkClass = DARK_BG_SVGS.has(slug) ? ' img--dark' : '';
      return `
        <button type="button" class="game-tile" data-game="${escapeHtml(game)}" aria-pressed="false">
          <div class="game-tile__image${darkClass}">
            <img src="${escapeHtml(logo)}" alt="${escapeHtml(game)}" loading="lazy"/>
          </div>
          <span class="game-tile__name">${escapeHtml(game)}</span>
        </button>`;
    }
    return `
      <button type="button" class="game-tile" data-game="${escapeHtml(game)}" aria-pressed="false">
        <div class="game-tile__icon" style="background:${color}; border-color:${color}">
          ${getGameInitial(game)}
        </div>
        <span class="game-tile__name">${escapeHtml(game)}</span>
      </button>`;
  }).join('');

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
// Platform Tiles (data-driven, clickable filter)
// ============================================================

function buildPlatformData(gamePlatforms) {
  const platformGames = {};
  for (const [game, platforms] of Object.entries(gamePlatforms)) {
    for (const p of platforms) {
      if (!platformGames[p]) platformGames[p] = [];
      platformGames[p].push(game);
    }
  }
  return platformGames;
}

function renderPlatformTiles(newsItems) {
  const hasSteam = newsItems.some(i => i.source && i.source.type === 'steam');
  const availablePlatforms = Object.keys(state.platformGames)
    .filter(p => state.platformGames[p].length > 0)
    .sort();

  const tiles = [];
  if (hasSteam) {
    tiles.push({ id: 'steam', src: 'assets/platforms/steam.svg', label: 'Steam' });
  }
  for (const p of availablePlatforms) {
    tiles.push({ id: p, src: PLATFORM_ICONS[p], label: PLATFORM_LABELS[p] });
  }

  if (tiles.length === 0) {
    els.platformSection.hidden = true;
    return;
  }

  els.platformSection.hidden = false;
  els.platformTiles.innerHTML = tiles.map(t => `
    <button type="button" class="game-tile" data-platform="${escapeHtml(t.id)}" aria-pressed="false">
      <div class="game-tile__image">
        <img src="${escapeHtml(t.src)}" alt="${escapeHtml(t.label)}" loading="lazy"/>
      </div>
      <span class="game-tile__name">${escapeHtml(t.label)}</span>
    </button>`).join('');

  els.platformTiles.querySelectorAll('.game-tile').forEach(tile => {
    tile.addEventListener('click', () => {
      const platform = tile.dataset.platform;
      if (state.filters.platforms.includes(platform)) {
        state.filters.platforms = state.filters.platforms.filter(p => p !== platform);
        tile.classList.remove('active');
        tile.setAttribute('aria-pressed', 'false');
      } else {
        state.filters.platforms.push(platform);
        tile.classList.add('active');
        tile.setAttribute('aria-pressed', 'true');
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
// Rendering — Gaming Pulse Card Design
// ============================================================

function renderNewsCard(item) {
  const category = item.category || '';
  const catColor = getCategoryColor(category);

  let mediaHtml;
  if (item.image_url) {
    mediaHtml = `<img src="${escapeHtml(item.image_url)}" alt="" class="news-card__image" loading="lazy"/>`;
  } else {
    const initials = getSourceInitials(item.source?.name);
    mediaHtml = `
      <div class="news-card__placeholder" style="--cat-color: ${catColor}">
        <span class="news-card__placeholder-initials">${escapeHtml(initials)}</span>
      </div>`;
  }

  const sourceBadge = getSourceBadge(item.source);
  const dateObj = new Date(item.published_at);
  const dateStr = formatDate(dateObj);
  const relStr = formatRelativeDate(dateObj);

  return `
    <article class="news-card" data-id="${item.id}" data-category="${category}">
      <div class="news-card__media">
        ${mediaHtml}
      </div>
      <div class="news-card__content">
        <div class="news-card__meta">
          ${sourceBadge}
          <time datetime="${dateObj.toISOString()}" title="${relStr}">${dateStr}</time>
        </div>
        <h3 class="news-card__title">
          <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">
            ${escapeHtml(item.title)}
          </a>
        </h3>
        ${item.summary ? `<p class="news-card__summary">${escapeHtml(item.summary)}</p>` : ''}
        <a href="${escapeHtml(item.url)}" class="news-card__link" target="_blank" rel="noopener noreferrer">
          LEER EN ${escapeHtml(item.source.name)} <span aria-hidden="true">\u2197</span>
        </a>
      </div>
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
  const { games, platforms, categories, search } = state.filters;

  state.filteredNews = state.allNews.filter(item => {
    if (search) {
      const query = search.toLowerCase();
      const haystack = `${item.title} ${item.summary || ''} ${item.game || ''}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }

    if (games.length > 0) {
      if (!item.game || !games.includes(item.game)) return false;
    }

    if (platforms.length > 0) {
      const hasSteamFilter = platforms.includes('steam');
      const otherPlatforms = platforms.filter(p => p !== 'steam');

      let platformPass = false;

      if (hasSteamFilter && item.source && item.source.type === 'steam') {
        platformPass = true;
      }

      if (otherPlatforms.length > 0 && item.game) {
        const gamePlats = state.gamePlatforms[item.game] || [];
        if (otherPlatforms.some(p => gamePlats.includes(p))) {
          platformPass = true;
        }
      }

      if (hasSteamFilter && otherPlatforms.length > 0) {
        const gamePlats = item.game ? (state.gamePlatforms[item.game] || []) : [];
        const steamMatch = item.source && item.source.type === 'steam';
        const platMatch = otherPlatforms.some(p => gamePlats.includes(p));
        platformPass = steamMatch && platMatch;
      }

      if (!platformPass) return false;
    }

    if (categories.length > 0) {
      if (!item.category || !categories.includes(item.category)) return false;
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

  els.platformTiles.querySelectorAll('.game-tile').forEach(tile => {
    const platform = tile.dataset.platform;
    const isActive = state.filters.platforms.includes(platform);
    tile.classList.toggle('active', isActive);
    tile.setAttribute('aria-pressed', String(isActive));
  });

  els.categoryPills.querySelectorAll('.category-pill').forEach(pill => {
    const cat = pill.dataset.cat;
    pill.classList.toggle('active', state.filters.categories.includes(cat));
  });

  els.search.value = state.filters.search || '';
}

// ============================================================
// URL Synchronization
// ============================================================

function filtersToUrlParams() {
  const params = new URLSearchParams();
  if (state.filters.games.length) params.set('game', state.filters.games.join(','));
  if (state.filters.platforms.length) params.set('platforms', state.filters.platforms.join(','));
  if (state.filters.categories.length) params.set('category', state.filters.categories.join(','));
  if (state.filters.search) params.set('q', state.filters.search);
  return params.toString();
}

function syncUrlToState() {
  const params = new URLSearchParams(window.location.search);
  state.filters.games = params.get('game')?.split(',').filter(Boolean) || [];
  state.filters.platforms = params.get('platforms')?.split(',').filter(Boolean) || [];
  state.filters.categories = params.get('category')?.split(',').filter(Boolean) || [];
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
  state.filters.search = els.search.value.trim();

  applyFilters();
  pushUrl();
}

function onClearFilters() {
  state.filters = {
    games: [],
    platforms: [],
    categories: [],
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
    state.gamePlatforms = gameData.platforms;
    state.platformGames = buildPlatformData(gameData.platforms);

    const configNames = gameData.names || new Set();
    const games = [...configNames].sort();
    renderGameTiles(games);
    renderPlatformTiles(data.news);
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
