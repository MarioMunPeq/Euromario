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

const PLATFORM_ICONS = {
  'pc-steam': 'assets/platforms/steam.svg',
  playstation: 'assets/platforms/playstation.svg',
  xbox: 'assets/platforms/xbox.svg',
  nintendo: 'assets/platforms/nintendo.svg',
};

const PLATFORM_LABELS = {
  'pc-steam': 'PC / Steam',
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
    game: null,
    platforms: [],
    category: null,
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
  filterPlatforms: document.getElementById('filter-platforms'),
  filterGames: document.getElementById('filter-games'),
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

function renderGameTiles(games) {
  const createTile = (game, isClone = false, cloneIndex = 0) => {
    const logo = state.gameLogos[game];
    const dataAttr = isClone ? `data-game-clone="${escapeHtml(game)}" data-clone-index="${cloneIndex}"` : `data-game="${escapeHtml(game)}"`;
    const ariaPressed = 'false';
    if (logo) {
      const slug = logo.split('/').pop().replace('.svg', '');
      const darkClass = DARK_BG_SVGS.has(slug) ? ' img--dark' : '';
      return `
        <button type="button" class="game-tile" ${dataAttr} aria-pressed="${ariaPressed}">
          <div class="game-tile__image${darkClass}">
            <img src="${escapeHtml(logo)}" alt="${escapeHtml(game)}" loading="lazy"/>
          </div>
          <span class="game-tile__name">${escapeHtml(game)}</span>
        </button>`;
    }
    return `
      <button type="button" class="game-tile" ${dataAttr} aria-pressed="${ariaPressed}">
        <div class="game-tile__icon">
          ${getGameInitial(game)}
        </div>
        <span class="game-tile__name">${escapeHtml(game)}</span>
      </button>`;
  };

  const gameTiles = games.map(game => createTile(game, false)).join('');

  if (TILES_MOBILE_MQL.matches && games.length > 0) {
    // Real section for infinite loop: [game1, game2, ..., gameN] (no "All")
    // We need clones on both sides that cover at least one viewport width.
    // TILE_WIDTH = 104px, so need at least 4 clones. Use min(5, games.length).
    const cloneCount = Math.min(5, games.length);

    const createCloneTile = (game, cloneIndex) => createTile(game, true, cloneIndex);

    // Left clones: last `cloneCount` games
    const lastClones = games.slice(-cloneCount).map((g, i) => createCloneTile(g, -(cloneCount - i))).join('');
    // Right clones: first `cloneCount` games
    const firstClones = games.slice(0, cloneCount).map((g, i) => createCloneTile(g, i)).join('');

    // DOM order: leftClones + realSection (games) + rightClones
    return lastClones + gameTiles + firstClones;
  }

  return gameTiles;
}

function renderPlatformTiles(newsItems) {
  const hasSteam = newsItems.some(i => getSourceType(i) === 'steam');
  const hasPCGames = (state.platformGames['pc'] || []).length > 0;
  const availablePlatforms = Object.keys(state.platformGames)
    .filter(p => state.platformGames[p].length > 0)
    .sort();

  const tiles = [];
  if (hasSteam || hasPCGames) {
    tiles.push({ id: 'pc-steam', src: 'assets/platforms/steam.svg', label: 'PC / Steam' });
  }
  for (const p of availablePlatforms) {
    if (p === 'pc') continue;
    tiles.push({ id: p, src: PLATFORM_ICONS[p], label: PLATFORM_LABELS[p] });
  }

  return tiles.map(t => `
    <button type="button" class="game-tile" data-platform="${escapeHtml(t.id)}" aria-pressed="false">
      <div class="game-tile__image">
        <img src="${escapeHtml(t.src)}" alt="${escapeHtml(t.label)}" loading="lazy"/>
      </div>
      <span class="game-tile__name">${escapeHtml(t.label)}</span>
    </button>`).join('');
}

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

function renderAllTiles(newsItems, games) {
  const platHtml = renderPlatformTiles(newsItems);
  const gameHtml = renderGameTiles(games);

  els.filterPlatforms.innerHTML = platHtml;
  els.filterGames.innerHTML = gameHtml;

  // Platform click handlers (multi-select)
  els.filterPlatforms.querySelectorAll('[data-platform]').forEach(tile => {
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

  // Game click handlers (single-select)
  // On desktop: simple click to filter
  // On mobile: carousel handles selection, clicks are for tap (no drag)
  const isMobile = TILES_MOBILE_MQL.matches;
  if (!isMobile) {
    // Desktop: attach click handlers directly
    els.filterGames.querySelectorAll('[data-game]').forEach(tile => {
      tile.addEventListener('click', () => {
        const game = tile.dataset.game;
        const wasActive = tile.classList.contains('active');

        els.filterGames.querySelectorAll('[data-game]').forEach(t => {
          t.classList.remove('active');
          t.setAttribute('aria-pressed', 'false');
        });

        if (wasActive) {
          state.filters.game = null;
        } else {
          state.filters.game = game;
          tile.classList.add('active');
          tile.setAttribute('aria-pressed', 'true');
        }
        applyFilters();
        pushUrl();
      });
    });
  } else {
    // Mobile: attach click handlers that work with carousel (tap without drag)
    // The carousel's pointer events handle drag/snap/selection
    // Click handler here is for tap-to-select when not dragging
    els.filterGames.querySelectorAll('[data-game], [data-game-clone]').forEach(tile => {
      tile.addEventListener('click', (e) => {
        // Only handle if not a drag (carousel handles drag-end selection)
        const game = tile.dataset.game || tile.dataset.gameClone;
        const wasActive = tile.classList.contains('active');

        els.filterGames.querySelectorAll('[data-game], [data-game-clone]').forEach(t => {
          t.classList.remove('active');
          t.setAttribute('aria-pressed', 'false');
        });

        if (wasActive) {
          state.filters.game = null;
        } else {
          state.filters.game = game;
          tile.classList.add('active');
          tile.setAttribute('aria-pressed', 'true');
          els.filterGames.querySelectorAll(`[data-game-clone="${escapeHtml(game)}"]`).forEach(clone => {
            clone.classList.add('active');
            clone.setAttribute('aria-pressed', 'true');
          });
        }
        applyFilters();
        pushUrl();
      });
    });
  }
}

// ============================================================
// Game Tiles Mobile Carousel (infinite loop + center selection)
// ============================================================

function setupGameTileCarousel() {
  const container = els.filterGames;
  if (!container) return;

  // Only run on mobile
  if (!TILES_MOBILE_MQL.matches) return;

  // Constants
  const TILE_WIDTH = 104; // 96px tile + 8px gap (from CSS)
  const DRAG_THRESHOLD = 8; // px — tap vs drag discrimination

  // State
  let rafId = 0;
  let activeTile = null;
  let isProgrammaticScroll = false;
  let dragState = null; // null | { startX, startScrollLeft, pointerId, moved }

  // Helpers
  const getRealGameName = (tile) => tile.dataset.game || tile.dataset.gameClone || '';

  // Dynamically compute clone zones from DOM structure
  // Real section = tiles with [data-game] (not clone) = real games only (no "All")
  const getRealSectionStart = () => {
    // First real tile is the first game (index 0 after left clones)
    const realTiles = container.querySelectorAll('[data-game]:not([data-game-clone])');
    if (realTiles.length === 0) return 0;
    const tiles = Array.from(container.querySelectorAll('.game-tile'));
    const index = tiles.indexOf(realTiles[0]);
    return index * TILE_WIDTH;
  };

  const getRealSectionEnd = () => {
    // Last real tile is the last [data-game] (not clone)
    const realTiles = container.querySelectorAll('[data-game]:not([data-game-clone])');
    if (realTiles.length === 0) return getRealSectionStart() + TILE_WIDTH;
    const lastReal = realTiles[realTiles.length - 1];
    const tiles = Array.from(container.querySelectorAll('.game-tile'));
    const index = tiles.indexOf(lastReal);
    return (index + 1) * TILE_WIDTH;
  };

  const getRealSectionWidth = () => getRealSectionEnd() - getRealSectionStart();

  const getLeftCloneZoneEnd = () => getRealSectionStart();

  const getRightCloneZoneStart = () => getRealSectionEnd();

  // --- Visual center tracking (runs on scroll, no side effects) ---
  const updateActiveTileVisual = () => {
    if (!TILES_MOBILE_MQL.matches || container.scrollWidth <= container.clientWidth + 1) {
      if (activeTile) {
        activeTile.classList.remove('is-active');
        activeTile = null;
      }
      return;
    }

    const centerX = container.getBoundingClientRect().left + container.clientWidth / 2;
    let best = null;
    let bestDist = Infinity;
    for (const tile of container.querySelectorAll('.game-tile')) {
      const rect = tile.getBoundingClientRect();
      const dist = Math.abs(rect.left + rect.width / 2 - centerX);
      if (dist < bestDist) {
        bestDist = dist;
        best = tile;
      }
    }

    if (best !== activeTile) {
      if (activeTile) activeTile.classList.remove('is-active');
      activeTile = best;
      if (activeTile) activeTile.classList.add('is-active');
    }
  };

  const scheduleUpdate = () => {
    if (!rafId) rafId = requestAnimationFrame(updateActiveTileVisual);
  };

  // --- Silent infinite loop wrapping ---
  const wrapIfNeeded = () => {
    const scrollLeft = container.scrollLeft;
    const leftZoneEnd = getLeftCloneZoneEnd();
    const rightZoneStart = getRightCloneZoneStart();
    const realWidth = getRealSectionWidth();

    let newScrollLeft = null;

    if (scrollLeft < leftZoneEnd) {
      newScrollLeft = scrollLeft + realWidth;
    } else if (scrollLeft > rightZoneStart) {
      newScrollLeft = scrollLeft - realWidth;
    }

    if (newScrollLeft !== null && newScrollLeft !== scrollLeft) {
      isProgrammaticScroll = true;
      container.style.scrollBehavior = 'auto';
      container.scrollLeft = newScrollLeft;
      requestAnimationFrame(() => {
        isProgrammaticScroll = false;
      });
    }
  };

  // --- Scroll observer (only visual updates) ---
  const onScroll = () => {
    if (isProgrammaticScroll) return;
    scheduleUpdate();
    // Also wrap during natural scroll (user flicks into clone zone)
    wrapIfNeeded();
  };

  // --- Pointer events (drag + tap) ---
  const onPointerDown = (e) => {
    if (e.button !== 0 && e.pointerType !== 'touch') return;
    if (e.target.closest('.game-tile') === null) return;

    dragState = {
      startX: e.clientX || (e.touches && e.touches[0].clientX),
      startScrollLeft: container.scrollLeft,
      pointerId: e.pointerId,
      moved: false,
    };

    container.style.scrollBehavior = 'auto';
    container.setPointerCapture?.(e.pointerId);
  };

  const onPointerMove = (e) => {
    if (!dragState || e.pointerId !== dragState.pointerId) return;

    const clientX = e.clientX || (e.touches && e.touches[0].clientX);
    if (clientX === undefined) return;

    const delta = dragState.startX - clientX;
    const moved = Math.abs(delta) > DRAG_THRESHOLD;

    if (moved && !dragState.moved) {
      dragState.moved = true;
      // Ensure no click handler fires after this
      container.style.userSelect = 'none';
    }

    if (dragState.moved) {
      e.preventDefault();
      container.scrollLeft = dragState.startScrollLeft + delta;
    }
  };

  const onPointerUp = (e) => {
    if (!dragState || e.pointerId !== dragState.pointerId) return;

    const wasDragging = dragState.moved;
    const pointerId = dragState.pointerId;
    dragState = null;

    container.releasePointerCapture?.(pointerId);
    container.style.userSelect = '';

    if (!wasDragging) {
      // Tap — let the click handler on the tile handle selection
      return;
    }

    // Drag ended — snap to nearest center, then wrap + select
    container.style.scrollBehavior = 'smooth';

    const finalizeSelection = () => {
      // 1. Wrap silently if needed
      wrapIfNeeded();

      // 2. Find tile visually centered NOW (after any wrap)
      const centerX = container.getBoundingClientRect().left + container.clientWidth / 2;
      let best = null;
      let bestDist = Infinity;
      for (const tile of container.querySelectorAll('.game-tile')) {
        const rect = tile.getBoundingClientRect();
        const dist = Math.abs(rect.left + rect.width / 2 - centerX);
        if (dist < bestDist) {
          bestDist = dist;
          best = tile;
        }
      }

      if (best) {
        const game = getRealGameName(best);

        // 3. Single source of truth: centered tile = selected filter
        if (state.filters.game !== game) {
          state.filters.game = game || null;
          applyFilters();
          pushUrl();
          syncFilterUIFromState();
        }

        // 4. Update visual active state to match
        if (activeTile) activeTile.classList.remove('is-active');
        activeTile = best;
        if (activeTile) activeTile.classList.add('is-active');
      }
    };

    // Wait for CSS scroll-snap to finish
    if ('onscrollend' in container) {
      const handler = () => {
        container.removeEventListener('scrollend', handler);
        finalizeSelection();
      };
      container.addEventListener('scrollend', handler, { once: true });
      // Safety timeout
      setTimeout(() => {
        container.removeEventListener('scrollend', handler);
        finalizeSelection();
      }, 500);
    } else {
      setTimeout(finalizeSelection, 350);
    }
  };

  const onPointerCancel = (e) => {
    if (!dragState || e.pointerId !== dragState.pointerId) return;
    container.releasePointerCapture?.(dragState.pointerId);
    container.style.userSelect = '';
    dragState = null;
  };

  // --- Event listeners ---
  container.addEventListener('scroll', onScroll, { passive: true });
  container.addEventListener('pointerdown', onPointerDown);
  container.addEventListener('pointermove', onPointerMove);
  container.addEventListener('pointerup', onPointerUp);
  container.addEventListener('pointercancel', onPointerCancel);
  container.addEventListener('pointerleave', onPointerCancel);

  window.addEventListener('resize', scheduleUpdate);
  if (TILES_MOBILE_MQL.addEventListener) TILES_MOBILE_MQL.addEventListener('change', scheduleUpdate);

  // --- Initial position: center first real game ---
  const firstRealTile = container.querySelector('[data-game]:not([data-game-clone])');
  if (firstRealTile) {
    const containerRect = container.getBoundingClientRect();
    const tileRect = firstRealTile.getBoundingClientRect();
    const targetScrollLeft = tileRect.left + tileRect.width / 2 - containerRect.left - container.clientWidth / 2;
    isProgrammaticScroll = true;
    container.style.scrollBehavior = 'auto';
    container.scrollLeft = targetScrollLeft;
    requestAnimationFrame(() => {
      isProgrammaticScroll = false;
    });
  }

  scheduleUpdate();
}

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

  let mediaHtml;
  if (item.image) {
    mediaHtml = `
      <img src="${escapeHtml(item.image)}" alt="" class="news-card__image" loading="lazy"/>
      <div class="news-card__overlay">
        <div class="news-card__overlay-content">
          <span class="news-card__section">${sectionLabel}</span>
          <span class="news-card__game">${escapeHtml(gameName.toUpperCase())}</span>
        </div>
      </div>`;
  } else {
    mediaHtml = `
      <div class="news-card__placeholder" style="--cat-color: ${catColor}">
        <span class="news-card__placeholder-initials">${escapeHtml(getSourceInitials(getSourceName(item.source, sourceType)))}</span>
      </div>
      <div class="news-card__overlay news-card__overlay--placeholder">
        <div class="news-card__overlay-content">
          <span class="news-card__section">${sectionLabel}</span>
          <span class="news-card__game">${escapeHtml(gameName.toUpperCase())}</span>
        </div>
      </div>`;
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
    state.filters.platforms.length ||
    state.filters.section
  );
}

function resetFilters() {
  state.filters.game = null;
  state.filters.platforms = [];
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
  const { game, platforms, category, section } = state.filters;

  state.filteredNews = state.allNews.filter(item => {
    if (game) {
      if (!item.game || item.game !== game) return false;
    }

    if (platforms.length > 0) {
      let platformPass = false;
      const hasUnified = platforms.includes('pc-steam');
      const otherPlatforms = platforms.filter(p => p !== 'pc-steam');

      if (hasUnified) {
        const isSteam = getSourceType(item) === 'steam';
        const isPC = item.game && (state.gamePlatforms[item.game] || []).includes('pc');
        if (isSteam || isPC) platformPass = true;
      }

      if (!platformPass && otherPlatforms.length > 0 && item.game) {
        const gamePlats = state.gamePlatforms[item.game] || [];
        if (otherPlatforms.some(p => gamePlats.includes(p))) {
          platformPass = true;
        }
      }

      if (!platformPass) return false;
    }

    // Section filter: NEWS = all except rumor, RUMORS = only rumor
    if (section === 'news') {
      if (item.category === 'rumor') return false;
    } else if (section === 'rumors') {
      if (item.category !== 'rumor') return false;
    }

    // Category sub-filter (works within NEWS section)
    if (category) {
      if (!item.category || item.category !== category) return false;
    }

    return true;
  });

  renderNewsList(state.filteredNews);
}

function syncFilterUIFromState() {
  const currentGame = state.filters.game || '';
  els.filterGames.querySelectorAll('[data-game], [data-game-clone]').forEach(tile => {
    const game = tile.dataset.game || tile.dataset.gameClone || '';
    const isActive = game === currentGame;
    tile.classList.toggle('active', isActive);
    tile.setAttribute('aria-pressed', String(isActive));
  });

  els.filterPlatforms.querySelectorAll('[data-platform]').forEach(tile => {
    const platform = tile.dataset.platform;
    const isActive = state.filters.platforms.includes(platform);
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
  if (state.filters.platforms.length) params.set('platforms', state.filters.platforms.join(','));
  if (state.filters.section) params.set('section', state.filters.section);
  return params.toString();
}

function syncUrlToState() {
  const params = new URLSearchParams(window.location.search);
  state.filters.game = params.get('game') || null;
  state.filters.platforms = params.get('platforms')?.split(',').filter(Boolean) || [];
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
    state.gamePlatforms = gameData.platforms;
    state.platformGames = buildPlatformData(gameData.platforms);

    const configNames = gameData.names || new Set();
    const games = [...configNames].sort();
    renderAllTiles(data.news, games);
    initHeaderNav();
    setupGameTileCarousel();

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
