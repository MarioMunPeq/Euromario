const puppeteer = require('puppeteer');
const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const FRONTEND_DIR = path.join(__dirname, '..', 'frontend');
const PORT = 8770;

function startServer() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const parsed = url.parse(req.url);
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

async function routeNews(page, respondFn, delay = 0) {
  await page.setRequestInterception(true);
  page.on('request', req => {
    if (/news\.json/.test(req.url())) {
      setTimeout(() => respondFn(req), delay);
    } else {
      req.continue();
    }
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
    // ============================================================
    // TEST E1: Estado loading — skeleton cards (sin spinner)
    // ============================================================
    console.log('\n=== TEST E1: Loading con skeleton cards ===');
    {
      const page = await browser.newPage();
      await page.setViewport({ width: 1280, height: 950 });
      const news = { news: [{ id: 1, title: 'Loaded', category: 'lanzamiento', source: 'IGN', published_at: '2026-01-01T00:00:00Z', relevance: 3 }] };
      await routeNews(page, req => req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(news) }), 1200);
      await page.goto(`http://localhost:${PORT}`, { waitUntil: 'domcontentloaded' });
      await new Promise(r => setTimeout(r, 500));
      const loading = await page.evaluate(() => {
        const l = document.getElementById('state-loading');
        return {
          loadingVisible: !l.hidden,
          skeletonCount: document.querySelectorAll('.skeleton-card').length,
          spinnerGone: !document.querySelector('.spinner'),
          label: document.querySelector('.state__label')?.textContent?.trim(),
        };
      });
      check('loading visible durante fetch', loading.loadingVisible);
      check('6 skeleton cards renderizadas', loading.skeletonCount === 6, `count=${loading.skeletonCount}`);
      check('spinner eliminado', loading.spinnerGone);
      check('etiqueta "Loading news…" presente', loading.label === 'Loading news…', `label=${loading.label}`);
      await page.screenshot({ path: 'test_states_loading.png' });
      await page.waitForFunction(() => !document.getElementById('news-list').hidden, { timeout: 5000 });
      const after = await page.evaluate(() => ({
        loadingHidden: document.getElementById('state-loading').hidden,
        contentVisible: !document.getElementById('news-list').hidden,
        cards: document.querySelectorAll('.news-card').length,
      }));
      check('loading oculto tras cargar', after.loadingHidden);
      check('contenido visible tras cargar', after.contentVisible);
      check('card renderizada', after.cards === 1, `cards=${after.cards}`);
      await page.close();
    }

    // ============================================================
    // TEST E2: Estado error + retry recupera
    // ============================================================
    console.log('\n=== TEST E2: Error con retry ===');
    {
      const page = await browser.newPage();
      await page.setViewport({ width: 1280, height: 950 });
      let failFirst = true;
      const news = { news: [{ id: 1, title: 'Recovered', category: 'rumor', source: 'Xbox Wire', published_at: '2026-01-02T00:00:00Z', relevance: 4 }] };
      await routeNews(page, req => {
        if (failFirst) {
          failFirst = false;
          req.respond({ status: 500, contentType: 'application/json', body: '{}' });
        } else {
          req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(news) });
        }
      });
      await page.goto(`http://localhost:${PORT}`, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => !document.getElementById('state-error').hidden, { timeout: 5000 });
      const err = await page.evaluate(() => {
        const e = document.getElementById('state-error');
        const style = getComputedStyle(e);
        return {
          errorVisible: !e.hidden,
          retryExists: !!document.getElementById('retry-btn'),
          title: document.getElementById('error-title')?.textContent?.trim(),
          panelSurface: style.background || style.backgroundColor,
          panelBorder: style.borderColor,
          radius: parseInt(style.borderRadius) > 0,
        };
      });
      check('estado error visible', err.errorVisible);
      check('botón retry presente', err.retryExists);
      check('error como panel editorial (surface+borde+radius)', err.panelSurface && err.panelBorder !== 'rgba(0, 0, 0, 0)' && err.radius, `radius=${err.radius}`);
      await page.click('#retry-btn');
      await page.waitForFunction(() => !document.getElementById('news-list').hidden, { timeout: 5000 });
      const after = await page.evaluate(() => ({
        errorHidden: document.getElementById('state-error').hidden,
        contentVisible: !document.getElementById('news-list').hidden,
        title: document.querySelector('.news-card__title')?.textContent?.trim(),
      }));
      check('retry oculta error', after.errorHidden);
      check('retry muestra contenido', after.contentVisible);
      check('card "Recovered" renderizada', after.title === 'Recovered', `title=${after.title}`);
      await page.screenshot({ path: 'test_states_error.png' });
      await page.close();
    }

    // ============================================================
    // TEST E3: Estado vacío (sin filtros → sin botón Clear)
    // ============================================================
    console.log('\n=== TEST E3: Vacío sin filtros ===');
    {
      const page = await browser.newPage();
      await page.setViewport({ width: 1280, height: 950 });
      await routeNews(page, req => req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify({ news: [] }) }));
      await page.goto(`http://localhost:${PORT}`, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => !document.getElementById('state-empty').hidden, { timeout: 5000 });
      const res = await page.evaluate(() => {
        const empty = document.getElementById('state-empty');
        const style = getComputedStyle(empty);
        return {
          emptyVisible: !empty.hidden,
          clearHidden: document.getElementById('clear-filters-btn').hidden,
          icon: !!empty.querySelector('.empty__icon'),
          panel: style.background && parseInt(style.borderRadius) > 0,
        };
      });
      check('estado vacío visible', res.emptyVisible);
      check('sin Clear filters (no hay filtros)', res.clearHidden);
      check('icono + panel editorial', res.icon && res.panel);
      await page.screenshot({ path: 'test_states_empty.png' });
      await page.close();
    }

    // ============================================================
    // TEST E4: Vacío con filtro activo → Clear filters lo limpia
    // ============================================================
    console.log('\n=== TEST E4: Vacío con filtro + Clear filters ===');
    {
      const page = await browser.newPage();
      await page.setViewport({ width: 1280, height: 950 });
      await routeNews(page, req => req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify({ news: [] }) }));
      await page.goto(`http://localhost:${PORT}?game=Zelda`, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => !document.getElementById('state-empty').hidden, { timeout: 5000 });
      const shown = await page.evaluate(() => ({
        emptyVisible: !document.getElementById('state-empty').hidden,
        clearVisible: !document.getElementById('clear-filters-btn').hidden,
      }));
      check('vacío visible', shown.emptyVisible);
      check('Clear filters visible con filtro activo', shown.clearVisible);

      await page.click('#clear-filters-btn');
      await new Promise(r => setTimeout(r, 300));
      const cleared = await page.evaluate(() => ({
        stillEmpty: !document.getElementById('state-empty').hidden,
        clearHiddenNow: document.getElementById('clear-filters-btn').hidden,
        url: location.search,
        gameTiles: [...document.querySelectorAll('[data-game]:not([data-game=""])')].filter(t => t.getAttribute('aria-pressed') === 'true').length,
      }));
      check('sigue vacío (datos vacíos)', cleared.stillEmpty);
      check('Clear filters oculto tras reset', cleared.clearHiddenNow);
      check('URL limpia (sin game)', cleared.url === '', `url="${cleared.url}"`);
      check('ningún tile de juego activo salvo "All"', cleared.gameTiles === 0, `active=${cleared.gameTiles}`);
      await page.screenshot({ path: 'test_states_empty_filtered.png' });
      await page.close();
    }

  } finally {
    await browser.close();
    server.close();
  }
  console.log(allPassed ? '\n=== TODAS LAS VERIFICACIONES DE ESTADOS PASARON ===' : '\n=== HAY FALLOS EN ESTADOS ===');
  process.exit(allPassed ? 0 : 1);
})();