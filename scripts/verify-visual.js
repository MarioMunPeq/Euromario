const puppeteer = require('puppeteer');
const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const FRONTEND_DIR = path.join(__dirname, '..', 'frontend');
const PORT = 8765;

function startServer() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const parsed = url.parse(req.url);
      let filePath = path.join(FRONTEND_DIR, parsed.pathname === '/' ? 'index.html' : parsed.pathname);
      const ext = path.extname(filePath);
      const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript', '.json': 'application/json', '.svg': 'image/svg+xml' };
      fs.readFile(filePath, (err, data) => {
        if (err) { res.writeHead(404); res.end('Not found'); return; }
        res.writeHead(200, { 'Content-Type': types[ext] || 'text/plain', 'Cache-Control': 'no-store' });
        res.end(data);
      });
    });
    server.listen(PORT, () => resolve(server));
  });
}

function saveScreenshot(page, name) {
  return page.screenshot({ path: path.join(__dirname, '..', `test_${name}.png`), fullPage: true });
}

async function getStateDiagnostics(page) {
  return page.evaluate(() => {
    const ids = ['state-loading', 'state-error', 'state-empty', 'news-list'];
    const result = {};
    for (const id of ids) {
      const el = document.getElementById(id);
      if (!el) { result[id] = { exists: false }; continue; }
      const r = el.getBoundingClientRect();
      const cs = window.getComputedStyle(el);
      result[id] = {
        exists: true,
        hidden: el.hidden,
        display: cs.display,
        width: Math.round(r.width),
        height: Math.round(r.height),
        visible: r.width > 0 && r.height > 0,
        childCount: el.children.length,
      };
    }
    const nl = document.getElementById('news-list');
    const firstCard = nl ? nl.querySelector('.news-card') : null;
    if (firstCard) {
      const cr = firstCard.getBoundingClientRect();
      result.firstCard = { width: Math.round(cr.width), height: Math.round(cr.height), visible: cr.width > 0 && cr.height > 0 };
      // Gaming Pulse card structure checks
      result.firstCard.hasMedia = !!firstCard.querySelector('.news-card__media');
      result.firstCard.hasContent = !!firstCard.querySelector('.news-card__content');
      result.firstCard.hasImage = !!firstCard.querySelector('.news-card__image');
      result.firstCard.hasPlaceholder = !!firstCard.querySelector('.news-card__placeholder');
      result.firstCard.hasTitle = !!firstCard.querySelector('.news-card__title a');
      result.firstCard.hasSummary = !!firstCard.querySelector('.news-card__summary');
      result.firstCard.hasLink = !!firstCard.querySelector('.news-card__link');
      result.firstCard.hasMeta = !!firstCard.querySelector('.news-card__meta');
      result.firstCard.dataCategory = firstCard.getAttribute('data-category');
    }
    const chain = [];
    let el = nl;
    while (el && el !== document.documentElement) {
      chain.push(el.id || el.tagName.toLowerCase());
      el = el.parentElement;
    }
    result.parentChain = chain;
    const hc = document.getElementById('header-count');
    result.headerCount = hc ? hc.textContent : 'NOT FOUND';
    // Game tiles check
    const tiles = document.querySelectorAll('.game-tile');
    result.gameTileCount = tiles.length;
    result.firstTileHasIcon = tiles.length > 0 ? !!tiles[0].querySelector('.game-tile__icon') : false;
    return result;
  });
}

(async () => {
  const server = await startServer();
  const browser = await puppeteer.launch({ headless: true });
  let allPassed = true;
  function check(label, condition) {
    const status = condition ? 'PASS' : 'FAIL';
    if (!condition) allPassed = false;
    console.log(`  [${status}] ${label}`);
  }

  try {
    // === TEST 1: Content state (normal load) ===
    console.log('\n=== TEST 1: Content state (normal load) ===');
    const page1 = await browser.newPage();
    await page1.setViewport({ width: 1280, height: 900 });
    await page1.goto(`http://localhost:${PORT}`, { waitUntil: 'networkidle0' });
    await new Promise(r => setTimeout(r, 500));
    const content = await getStateDiagnostics(page1);

    check('parentChain: news-list is child of news-grid', content.parentChain[0] === 'news-list' && content.parentChain[1] === 'news-grid');
    check('news-list hidden=false', content['news-list'].hidden === false);
    check('news-list display=grid', content['news-list'].display === 'grid');
    check('news-list width > 0', content['news-list'].width > 0);
    check('news-list height > 0', content['news-list'].height > 0);
    check('news-list has children', content['news-list'].childCount > 0);
    check('first card visible', content.firstCard && content.firstCard.visible);
    check('first card width > 0', content.firstCard && content.firstCard.width > 0);
    check('first card height > 0', content.firstCard && content.firstCard.height > 0);
    check('loading hidden', content['state-loading'].hidden === true);
    check('error hidden', content['state-error'].hidden === true);
    check('empty hidden', content['state-empty'].hidden === true);
    check('header shows noticias', content.headerCount.includes('noticias'));
    // Gaming Pulse card structure
    check('card has media section', content.firstCard && content.firstCard.hasMedia);
    check('card has content section', content.firstCard && content.firstCard.hasContent);
    check('card has image or placeholder', content.firstCard && (content.firstCard.hasImage || content.firstCard.hasPlaceholder));
    check('card has title link', content.firstCard && content.firstCard.hasTitle);
    check('card has LEER EN link', content.firstCard && content.firstCard.hasLink);
    check('card has meta (source+date)', content.firstCard && content.firstCard.hasMeta);
    check('card has data-category', content.firstCard && !!content.firstCard.dataCategory);
    // Game tiles
    check('game tiles rendered', content.gameTileCount > 0);
    check('first tile (ALL) has icon', content.firstTileHasIcon);
    console.log('  Parent chain:', content.parentChain.join(' > '));
    console.log('  News-list dimensions:', content['news-list'].width + 'x' + content['news-list'].height);
    console.log('  First card dimensions:', content.firstCard ? content.firstCard.width + 'x' + content.firstCard.height : 'N/A');
    console.log('  Card structure: media=' + (content.firstCard ? content.firstCard.hasMedia : 'N/A') + ' content=' + (content.firstCard ? content.firstCard.hasContent : 'N/A'));
    console.log('  Game tiles:', content.gameTileCount);
    await saveScreenshot(page1, 'content');
    await page1.close();

    // === TEST 2: Error state (404 on news.json) ===
    console.log('\n=== TEST 2: Error state ===');
    const ctx2 = await browser.createBrowserContext();
    const page2 = await ctx2.newPage();
    await page2.setViewport({ width: 1280, height: 900 });
    await page2.setRequestInterception(true);
    page2.on('request', req => {
      if (req.url().includes('news.json')) {
        req.respond({ status: 404, body: 'Not found' });
      } else {
        req.continue();
      }
    });
    await page2.goto(`http://localhost:${PORT}`, { waitUntil: 'networkidle0' });
    await new Promise(r => setTimeout(r, 1500));
    const errorState = await getStateDiagnostics(page2);

    check('error state visible (not hidden)', errorState['state-error'].hidden === false);
    check('error state has display', errorState['state-error'].display !== 'none');
    check('news-list hidden', errorState['news-list'].hidden === true);
    check('loading hidden', errorState['state-loading'].hidden === true);
    check('empty hidden', errorState['state-empty'].hidden === true);
    await saveScreenshot(page2, 'error');
    await ctx2.close();

    // === TEST 3: Empty state (empty news array) ===
    console.log('\n=== TEST 3: Empty state ===');
    const ctx3 = await browser.createBrowserContext();
    const page3 = await ctx3.newPage();
    await page3.setViewport({ width: 1280, height: 900 });
    const emptyNews = JSON.stringify({ generated_at: new Date().toISOString(), news: [] });
    await page3.setRequestInterception(true);
    page3.on('request', req => {
      if (req.url().includes('news.json')) {
        req.respond({ status: 200, contentType: 'application/json', body: emptyNews });
      } else {
        req.continue();
      }
    });
    await page3.goto(`http://localhost:${PORT}`, { waitUntil: 'networkidle0' });
    await new Promise(r => setTimeout(r, 1500));
    const emptyDiag = await getStateDiagnostics(page3);

    check('empty state visible (not hidden)', emptyDiag['state-empty'].hidden === false);
    check('empty state has display', emptyDiag['state-empty'].display !== 'none');
    check('news-list hidden', emptyDiag['news-list'].hidden === true);
    check('loading hidden', emptyDiag['state-loading'].hidden === true);
    check('error hidden', emptyDiag['state-error'].hidden === true);
    await saveScreenshot(page3, 'empty');
    await ctx3.close();

    // === TEST 4: Loading state (delayed response) ===
    console.log('\n=== TEST 4: Loading state ===');
    const ctx4 = await browser.createBrowserContext();
    const page4 = await ctx4.newPage();
    await page4.setViewport({ width: 1280, height: 900 });
    await page4.setRequestInterception(true);
    page4.on('request', req => {
      if (req.url().includes('news.json')) {
        setTimeout(() => req.continue(), 8000);
      } else {
        req.continue();
      }
    });
    await page4.goto(`http://localhost:${PORT}`, { waitUntil: 'domcontentloaded' });
    await new Promise(r => setTimeout(r, 500));
    const loadingDiag = await getStateDiagnostics(page4);

    check('loading state visible (not hidden)', loadingDiag['state-loading'].hidden === false);
    check('loading state has display', loadingDiag['state-loading'].display !== 'none');
    check('news-list hidden during loading', loadingDiag['news-list'].hidden === true);
    check('error hidden during loading', loadingDiag['state-error'].hidden === true);
    check('empty hidden during loading', loadingDiag['state-empty'].hidden === true);
    await saveScreenshot(page4, 'loading');
    await ctx4.close();

  } finally {
    await browser.close();
    server.close();
  }

  console.log(allPassed ? '\n=== ALL TESTS PASSED ===' : '\n=== SOME TESTS FAILED ===');
  process.exit(allPassed ? 0 : 1);
})();
