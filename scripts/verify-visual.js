const puppeteer = require('puppeteer');
const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const FRONTEND_DIR = path.join(__dirname, 'frontend');
const PORT = 8765;

function startServer() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const parsed = url.parse(req.url);
      let filePath = path.join(FRONTEND_DIR, parsed.pathname === '/' ? 'index.html' : parsed.pathname);
      const ext = path.extname(filePath);
      const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript', '.json': 'application/json' };
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
  return page.screenshot({ path: path.join(__dirname, `test_${name}.png`), fullPage: true });
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

    check('parentChain: news-list is child of news-grid (not state-empty)', content.parentChain[0] === 'news-list' && content.parentChain[1] === 'news-grid');
    check('news-list hidden=false', content['news-list'].hidden === false);
    check('news-list display=grid', content['news-list'].display === 'grid');
    check('news-list width > 0', content['news-list'].width > 0);
    check('news-list height > 0', content['news-list'].height > 0);
    check('news-list has 10 children', content['news-list'].childCount === 10);
    check('first card visible', content.firstCard && content.firstCard.visible);
    check('first card width > 0', content.firstCard && content.firstCard.width > 0);
    check('first card height > 0', content.firstCard && content.firstCard.height > 0);
    check('loading hidden', content['state-loading'].hidden === true);
    check('error hidden', content['state-error'].hidden === true);
    check('empty hidden', content['state-empty'].hidden === true);
    check('header shows 10 noticias', content.headerCount === '10 noticias');
    console.log('  Parent chain:', content.parentChain.join(' > '));
    console.log('  News-list dimensions:', content['news-list'].width + 'x' + content['news-list'].height);
    console.log('  First card dimensions:', content.firstCard ? content.firstCard.width + 'x' + content.firstCard.height : 'N/A');
    await saveScreenshot(page1, 'content');
    await page1.close();

    // === TEST 2: Error state (fetch fails) ===
    console.log('\n=== TEST 2: Error state ===');
    const page2 = await browser.newPage();
    await page2.setViewport({ width: 1280, height: 900 });
    // Directly trigger error state via JS
    await page2.goto(`http://localhost:${PORT}`, { waitUntil: 'networkidle0' });
    await new Promise(r => setTimeout(r, 500));
    await page2.evaluate(() => {
      setError('No se encontraron noticias.', 'No se pudieron cargar las noticias');
    });
    await new Promise(r => setTimeout(r, 300));
    const errorState = await getStateDiagnostics(page2);

    check('error state visible (not hidden)', errorState['state-error'].hidden === false);
    check('error state has display', errorState['state-error'].display !== 'none');
    check('news-list hidden', errorState['news-list'].hidden === true);
    check('loading hidden', errorState['state-loading'].hidden === true);
    check('empty hidden', errorState['state-empty'].hidden === true);
    await saveScreenshot(page2, 'error');
    await page2.close();

    // === TEST 3: Empty state (empty news array) ===
    console.log('\n=== TEST 3: Empty state ===');
    const page3 = await browser.newPage();
    await page3.setViewport({ width: 1280, height: 900 });
    await page3.goto(`http://localhost:${PORT}`, { waitUntil: 'networkidle0' });
    await new Promise(r => setTimeout(r, 500));
    // Directly trigger empty state via JS (avoids request interception issues)
    await page3.evaluate(() => {
      setState('empty');
    });
    await new Promise(r => setTimeout(r, 300));
    const emptyDiag = await getStateDiagnostics(page3);

    check('empty state visible (not hidden)', emptyDiag['state-empty'].hidden === false);
    check('empty state has display', emptyDiag['state-empty'].display !== 'none');
    check('news-list hidden', emptyDiag['news-list'].hidden === true);
    check('loading hidden', emptyDiag['state-loading'].hidden === true);
    check('error hidden', emptyDiag['state-error'].hidden === true);
    await saveScreenshot(page3, 'empty');
    await page3.close();

    // === TEST 4: Loading state (throttled network) ===
    console.log('\n=== TEST 4: Loading state ===');
    const page4 = await browser.newPage();
    await page4.setViewport({ width: 1280, height: 900 });
    // Trigger loading state directly via JS
    await page4.goto(`http://localhost:${PORT}`, { waitUntil: 'domcontentloaded' });
    await new Promise(r => setTimeout(r, 50));
    await page4.evaluate(() => {
      setLoading(true);
    });
    await new Promise(r => setTimeout(r, 100));
    const loadingDiag = await getStateDiagnostics(page4);

    check('loading state visible (not hidden)', loadingDiag['state-loading'].hidden === false);
    check('loading state has display', loadingDiag['state-loading'].display !== 'none');
    check('news-list hidden during loading', loadingDiag['news-list'].hidden === true);
    check('error hidden during loading', loadingDiag['state-error'].hidden === true);
    check('empty hidden during loading', loadingDiag['state-empty'].hidden === true);
    await saveScreenshot(page4, 'loading');
    await page4.close();

  } finally {
    await browser.close();
    server.close();
  }

  console.log(allPassed ? '\n=== ALL TESTS PASSED ===' : '\n=== SOME TESTS FAILED ===');
  process.exit(allPassed ? 0 : 1);
})();
