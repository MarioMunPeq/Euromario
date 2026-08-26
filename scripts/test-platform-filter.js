const puppeteer = require('puppeteer');
const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const FRONTEND_DIR = path.join(__dirname, '..', 'frontend');
const PORT = 8770;

(async () => {
  const server = http.createServer((req, res) => {
    const parsed = url.parse(req.url);
    let fp = path.join(FRONTEND_DIR, parsed.pathname === '/' ? 'index.html' : parsed.pathname);
    const ext = path.extname(fp);
    const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript', '.json': 'application/json', '.svg': 'image/svg+xml' };
    fs.readFile(fp, (err, data) => { if (err) { res.writeHead(404); res.end('Not found'); return; } res.writeHead(200, { 'Content-Type': types[ext] || 'text/plain', 'Cache-Control': 'no-store' }); res.end(data); });
  });
  await new Promise(r => server.listen(PORT, r));
  const browser = await puppeteer.launch({ headless: 'new' });
  let passed = 0, failed = 0;
  function check(label, condition) { if (condition) { passed++; console.log('  [PASS] ' + label); } else { failed++; console.log('  [FAIL] ' + label); } }

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 900 });
    await page.goto('http://localhost:' + PORT, { waitUntil: 'networkidle0' });
    await new Promise(r => setTimeout(r, 1000));

    // TEST 1: Platform section visible with tiles
    console.log('\n=== TEST 1: Platform section ===');
    const s1 = await page.evaluate(() => {
      const section = document.getElementById('platform-section');
      const tiles = document.querySelectorAll('#platform-tiles .game-tile');
      return {
        hidden: section?.hidden,
        tileCount: tiles.length,
        tiles: Array.from(tiles).map(t => ({
          tag: t.tagName,
          platform: t.dataset.platform,
          text: t.textContent.trim(),
          isButton: t.tagName === 'BUTTON',
          hasImg: !!t.querySelector('img'),
          imgSrc: t.querySelector('img')?.getAttribute('src'),
        })),
      };
    });
    check('platform section not hidden', !s1.hidden);
    check('has platform tiles', s1.tileCount > 0);
    s1.tiles.forEach(t => {
      check(t.text + ' is BUTTON', t.isButton);
      check(t.text + ' has data-platform', !!t.platform);
      check(t.text + ' has image', t.hasImg);
    });
    console.log('  Tiles:', s1.tiles.map(t => t.text + '(' + t.platform + ')').join(', '));

    // TEST 2: Visual parity with game tiles
    console.log('\n=== TEST 2: Visual parity ===');
    const s2 = await page.evaluate(() => {
      const gameTile = document.querySelector('#game-tiles .game-tile:not([data-game=""])');
      const platformTile = document.querySelector('#platform-tiles .game-tile');
      if (!gameTile || !platformTile) return null;
      const gcs = getComputedStyle(gameTile);
      const pcs = getComputedStyle(platformTile);
      return {
        game: { borderStyle: gcs.borderStyle, opacity: gcs.opacity, cursor: gcs.cursor },
        platform: { borderStyle: pcs.borderStyle, opacity: pcs.opacity, cursor: pcs.cursor },
      };
    });
    if (s2) {
      check('platform border-style = game (' + s2.game.borderStyle + ')', s2.platform.borderStyle === s2.game.borderStyle);
      check('platform opacity = game (' + s2.game.opacity + ')', s2.platform.opacity === s2.game.opacity);
      check('platform cursor = pointer', s2.platform.cursor === 'pointer');
    }

    // TEST 3: Click toggle
    console.log('\n=== TEST 3: Click toggle ===');
    const steamTile = await page.$('#platform-tiles [data-platform="steam"]');
    if (steamTile) {
      await steamTile.click();
      await new Promise(r => setTimeout(r, 200));
      const afterClick = await page.evaluate(() => {
        const t = document.querySelector('#platform-tiles [data-platform="steam"]');
        return { active: t.classList.contains('active'), pressed: t.getAttribute('aria-pressed') };
      });
      check('steam active after click', afterClick.active);
      check('steam aria-pressed=true', afterClick.pressed === 'true');

      await steamTile.click();
      await new Promise(r => setTimeout(r, 200));
      const afterUn = await page.evaluate(() => {
        const t = document.querySelector('#platform-tiles [data-platform="steam"]');
        return { active: t.classList.contains('active'), pressed: t.getAttribute('aria-pressed') };
      });
      check('steam inactive after 2nd click', !afterUn.active);
      check('steam aria-pressed=false', afterUn.pressed === 'false');
    }

    // TEST 4: Filter effect
    console.log('\n=== TEST 4: Filter effect ===');
    const beforeCount = await page.evaluate(() => document.querySelectorAll('.news-card').length);
    if (steamTile) {
      await steamTile.click();
      await new Promise(r => setTimeout(r, 300));
      const afterCount = await page.evaluate(() => document.querySelectorAll('.news-card').length);
      check('steam filter reduces count (' + beforeCount + ' -> ' + afterCount + ')', afterCount <= beforeCount);
      check('cards remain > 0', afterCount > 0);
      await steamTile.click();
      await new Promise(r => setTimeout(r, 200));
    }

    // TEST 5: URL sync
    console.log('\n=== TEST 5: URL sync ===');
    if (steamTile) {
      await steamTile.click();
      await new Promise(r => setTimeout(r, 200));
      const urlHas = await page.evaluate(() => window.location.search.includes('platforms=steam'));
      check('URL contains platforms=steam', urlHas);
      await steamTile.click();
      await new Promise(r => setTimeout(r, 200));
    }

    // TEST 6: AND combination
    console.log('\n=== TEST 6: AND combination ===');
    const gameTile = await page.$('#game-tiles [data-game="Persona"]');
    if (steamTile && gameTile) {
      await steamTile.click();
      await new Promise(r => setTimeout(r, 200));
      const steamOnly = await page.evaluate(() => document.querySelectorAll('.news-card').length);
      await gameTile.click();
      await new Promise(r => setTimeout(r, 200));
      const combined = await page.evaluate(() => document.querySelectorAll('.news-card').length);
      check('AND narrower than platform alone (' + steamOnly + ' -> ' + combined + ')', combined <= steamOnly);
      await gameTile.click();
      await steamTile.click();
      await new Promise(r => setTimeout(r, 200));
    }

    // Screenshots
    await page.screenshot({ path: 'diag_platform_final.png', fullPage: false });
    await page.evaluate(() => window.scrollTo(0, 350));
    await new Promise(r => setTimeout(r, 300));
    await page.screenshot({ path: 'diag_platform_cards.png', fullPage: false });

    console.log('\n=== RESULTS: ' + passed + ' passed, ' + failed + ' failed ===');
  } finally {
    await browser.close();
    server.close();
  }
  process.exit(failed > 0 ? 1 : 0);
})();
