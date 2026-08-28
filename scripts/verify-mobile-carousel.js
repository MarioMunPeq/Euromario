const puppeteer = require('puppeteer');
const http = require('http');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

const FRONTEND_DIR = path.join(__dirname, '..', 'frontend');
const PORT = 8769;

function startServer() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const parsed = new URL(req.url, `http://localhost:${PORT}`);
      let filePath = path.join(FRONTEND_DIR, parsed.pathname === '/' ? 'index.html' : parsed.pathname);
      const ext = path.extname(filePath);
      const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon' };
      fs.readFile(filePath, (err, data) => {
        if (err) { res.writeHead(404); res.end('Not found'); return; }
        res.writeHead(200, { 'Content-Type': types[ext] || 'text/plain', 'Cache-Control': 'no-store' });
        res.end(data);
      });
    });
    server.listen(PORT, () => resolve(server));
  });
}

(async () => {
  const server = await startServer();
  const browser = await puppeteer.launch({ headless: true });
  let allPassed = true;
  function check(label, condition, info) {
    const status = condition ? 'PASS' : 'FAIL';
    if (!condition) allPassed = false;
    console.log(`  [${status}] ${label}${info ? ' — ' + info : ''}`);
  }

  try {
    const page = await browser.newPage();

    // ============================================================
    // MOBILE (375px)
    // ============================================================
    await page.setViewport({ width: 375, height: 812 });
    await page.goto(`http://localhost:${PORT}/?v=${Date.now()}`, { waitUntil: 'networkidle0' });
    await new Promise(r => setTimeout(r, 900));

    console.log('=== MÓVIL 375px: Clear eliminado ===');
    const noClear = await page.evaluate(() => ({
      noClearBtn: !document.getElementById('clear-filters'),
      noActions: !document.querySelector('.filters__actions'),
      noGhost: !document.querySelector('.btn--ghost'),
    }));
    check('sin #clear-filters', noClear.noClearBtn);
    check('sin .filters__actions', noClear.noActions);
    check('sin .btn--ghost', noClear.noGhost);

    console.log('\n=== MÓVIL 375px: carrusel de juegos ===');
    const layout = await page.evaluate(() => {
      const games = document.getElementById('filter-games');
      const platforms = document.getElementById('filter-platforms');
      const gs = getComputedStyle(games);
      const ps = getComputedStyle(platforms);
      const firstTile = games.querySelector('.game-tile');
      return {
        gamesDisplay: gs.display,
        gamesWrap: gs.flexWrap,
        gamesOverflowX: gs.overflowX,
        gamesSnap: gs.scrollSnapType,
        scrollbarWidth: gs.scrollbarWidth,
        tileWidth: firstTile ? firstTile.getBoundingClientRect().width : 0,
        tileSnapAlign: firstTile ? getComputedStyle(firstTile).scrollSnapAlign : null,
        platformsDisplay: ps.display,
        platformsOverflow: ps.overflowX,
        tileCount: games.querySelectorAll('.game-tile').length,
      };
    });
    check('juegos son fila horizontal (flex nowrap)', layout.gamesDisplay === 'flex' && layout.gamesWrap === 'nowrap', `display=${layout.gamesDisplay} wrap=${layout.gamesWrap}`);
    check('juegos con scroll-x', layout.gamesOverflowX === 'auto', `overflowX=${layout.gamesOverflowX}`);
    check('scroll-snap sobre el eje x', layout.gamesSnap.includes('x'), `snap=${layout.gamesSnap}`);
    check('barra de scroll oculta', layout.scrollbarWidth === 'none', `scrollbarWidth=${layout.scrollbarWidth}`);
    check('tile ancho ~96px', layout.tileWidth >= 94 && layout.tileWidth <= 98, `width=${layout.tileWidth.toFixed(1)}px`);
    check('tile snap-align center', layout.tileSnapAlign === 'center', `align=${layout.tileSnapAlign}`);
    check('plataformas siguen en grid con wrap', layout.platformsDisplay === 'grid', `display=${layout.platformsDisplay}`);
    check('al menos 16 tiles de juego', layout.tileCount >= 16, `count=${layout.tileCount}`);

    console.log('=== MÓVIL 375px: header en una sola fila ===');
    const headerLayout = await page.evaluate(() => {
      const brand = document.querySelector('.header__brand').getBoundingClientRect();
      const nav = document.querySelector('.header__nav').getBoundingClientRect();
      const logo = document.querySelector('.header__logo').getBoundingClientRect();
      const btn = document.querySelector('.header__nav-btn').getBoundingClientRect();
      return {
        innerWrap: getComputedStyle(document.querySelector('.header__inner')).flexWrap,
        sameRow: Math.abs(brand.top - nav.top) < 8,
        btnSameRowAsLogo: Math.abs(logo.top - btn.top) < 8,
        navRightOfBrand: nav.left >= brand.right - 2,
      };
    });
    check('header sin wrap', headerLayout.innerWrap === 'nowrap', `flexWrap=${headerLayout.innerWrap}`);
    check('logo y nav en la misma fila', headerLayout.sameRow);
    check('botones en la misma fila que el logo', headerLayout.btnSameRowAsLogo);
    check('nav a la derecha del logo', headerLayout.navRightOfBrand);

    const snapshot = async () => page.evaluate(() => {
      const games = document.getElementById('filter-games');
      const centerX = games.getBoundingClientRect().left + games.clientWidth / 2;
      const tiles = [...games.querySelectorAll('.game-tile')];
      const measurements = tiles.map(t => {
        const r = t.getBoundingClientRect();
        return {
          name: t.querySelector('.game-tile__name').textContent.trim(),
          center: r.left + r.width / 2,
          dist: Math.abs(r.left + r.width / 2 - centerX),
          active: t.classList.contains('is-active'),
          transform: getComputedStyle(t).transform,
        };
      });
      const pre = (m) => {
        if (m === 'none') return 1;
        const parts = m.match(/matrix\(([^)]+)\)/);
        if (!parts) return null;
        return parseFloat(parts[1].split(',')[0]);
      };
      const actives = measurements.filter(m => m.active);
      const nearest = measurements.reduce((a, b) => (a.dist < b.dist ? a : b));
      return {
        actives: actives.map(a => a.name),
        nearestName: nearest.name,
        nearestDist: +nearest.dist.toFixed(1),
        scaleActive: actives.length ? pre(actives[0].transform) : null,
        scaleNeighbor: measurements.filter(m => !m.active)[0] ? pre(measurements.filter(m => !m.active)[0].transform) : null,
        scrollLeft: games.scrollLeft,
      };
    });

    console.log('\n=== MÓVIL 375px: efecto de centro (scroll) ===');
    await page.evaluate(() => {
      const games = document.getElementById('filter-games');
      games.scrollLeft = 200;
      games.dispatchEvent(new Event('scroll'));
    });
    await new Promise(r => setTimeout(r, 320));
    let s = await snapshot();
    check('un solo tile .is-active', s.actives.length === 1, `activos=${JSON.stringify(s.actives)}`);
    check('el activo es el más cercano al centro', s.actives[0] === s.nearestName, `activo=${s.actives[0]} nearest=${s.nearestName} (dist ${s.nearestDist})`);
    check('tile activo escala ~1.12', s.scaleActive !== null && Math.abs(s.scaleActive - 1.12) < 0.02, `scale=${s.scaleActive}`);
    check('tile lateral sin escala', s.scaleNeighbor === 1 || s.scaleNeighbor === null, `scale=${s.scaleNeighbor}`);

    console.log('\n=== MÓVIL 375px: tile activo no recortado (padding vertical) ===');
    const fit = await page.evaluate(() => {
      const container = document.getElementById('filter-games');
      const cr = container.getBoundingClientRect();
      const active = container.querySelector('.game-tile.is-active');
      if (!active) return { ok: false, reason: 'sin tile activo' };
      const ar = active.getBoundingClientRect();
      return {
        containerTop: +cr.top.toFixed(1),
        activeTop: +ar.top.toFixed(1),
        containerBottom: +cr.bottom.toFixed(1),
        activeBottom: +ar.bottom.toFixed(1),
        contained: ar.top >= cr.top - 1 && ar.bottom <= cr.bottom + 1,
      };
    });
    check('tile activo cabe dentro del contenedor', fit.contained, `top ${fit.activeTop} >= ${fit.containerTop} | bottom ${fit.activeBottom} <= ${fit.containerBottom}`);
    await page.screenshot({ path: path.join(__dirname, '..', 'test_tiles_carousel_375_fit.png') });
    await page.screenshot({ path: path.join(__dirname, '..', 'test_tiles_carousel_375_scroll200.png') });

    await page.evaluate(() => {
      const games = document.getElementById('filter-games');
      games.scrollLeft = 500;
      games.dispatchEvent(new Event('scroll'));
    });
    await new Promise(r => setTimeout(r, 320));
    s = await snapshot();
    check('el activo cambia al hacer scroll (scrollLeft≈500)', s.actives.length === 1 && s.scrollLeft >= 400, `activo=${JSON.stringify(s.actives)} scrollLeft=${s.scrollLeft}`);
    check('activo sigue siendo el más cercano al centro', s.actives[0] === s.nearestName, `activo=${s.actives[0]} nearest=${s.nearestName}`);
    await page.screenshot({ path: path.join(__dirname, '..', 'test_tiles_carousel_375_scroll500.png') });

    // ============================================================
    // DESKTOP (1280px): sin efecto
    // ============================================================
    console.log('\n=== DESKTOP 1280px: grid con wrap, sin efecto ===');
    await page.setViewport({ width: 1280, height: 950 });
    await new Promise(r => setTimeout(r, 320));
    const desktop = await page.evaluate(() => {
      const games = document.getElementById('filter-games');
      const gs = getComputedStyle(games);
      return {
        display: gs.display,
        overflowX: gs.overflowX,
        gridTemplate: gs.gridTemplateColumns,
        anyIsActive: games.querySelectorAll('.is-active').length,
        transforms: [...games.querySelectorAll('.game-tile')].map(t => getComputedStyle(t).transform).filter(t => t !== 'none').length,
      };
    });
    check('desktop: grid con wrap', desktop.display === 'grid', `display=${desktop.display}`);
    check('desktop: sin overflow-x', desktop.overflowX === 'visible', `overflowX=${desktop.overflowX}`);
    check('desktop: grid multi-columna', desktop.gridTemplate.split(' ').length >= 3, `template=${desktop.gridTemplate}`);
    check('desktop: sin .is-active', desktop.anyIsActive === 0);
    check('desktop: sin transforms aplicados', desktop.transforms === 0, `transforms=${desktop.transforms}`);

  } finally {
    await browser.close();
    server.close();
  }
  console.log(allPassed ? '\n=== TODAS LAS VERIFICACIONES PASARON ===' : '\n=== HAY FALLOS ===');
  process.exit(allPassed ? 0 : 1);
})();