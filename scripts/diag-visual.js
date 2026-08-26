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

(async () => {
  const server = await startServer();
  const browser = await puppeteer.launch({ headless: 'new' });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 900 });
    page.on('console', msg => console.log('BROWSER:', msg.text()));

    await page.goto(`http://localhost:${PORT}`, { waitUntil: 'networkidle0' });
    await new Promise(r => setTimeout(r, 1000));

    // 1. Game tiles container
    const gameTilesInfo = await page.evaluate(() => {
      const container = document.getElementById('game-tiles');
      if (!container) return { found: false };
      const children = Array.from(container.children);
      return {
        found: true,
        childCount: children.length,
        children: children.map(c => ({
          tag: c.tagName,
          classList: Array.from(c.classList),
          text: c.textContent.trim().substring(0, 60),
          hasImg: !!c.querySelector('img'),
          imgSrc: c.querySelector('img')?.getAttribute('src') || 'none',
          imgNaturalWidth: c.querySelector('img')?.naturalWidth || 0,
          imgComplete: c.querySelector('img')?.complete,
        })),
      };
    });
    console.log('\n=== #game-tiles ===');
    console.log('Found:', gameTilesInfo.found, '| Children:', gameTilesInfo.childCount);
    if (gameTilesInfo.found) {
      gameTilesInfo.children.forEach((c, i) => {
        console.log(`  [${i}] <${c.tag}> class="${c.classList.join(' ')}" text="${c.text}" img=${c.hasImg} imgSrc=${c.imgSrc} naturalW=${c.imgNaturalWidth} complete=${c.imgComplete}`);
      });
    }

    // 2. Platform tiles
    const platformInfo = await page.evaluate(() => {
      const pts = document.querySelectorAll('.platform-tile');
      return Array.from(pts).map(t => ({
        text: t.textContent.trim(),
        imgSrc: t.querySelector('img')?.getAttribute('src') || 'none',
        imgNaturalWidth: t.querySelector('img')?.naturalWidth || 0,
        imgComplete: t.querySelector('img')?.complete,
        imgNw: t.querySelector('img')?.naturalWidth,
        imgNh: t.querySelector('img')?.naturalHeight,
        imgSrcEmpty: !t.querySelector('img')?.src,
        parentTag: t.parentElement?.tagName,
        parentClass: t.parentElement?.className,
      }));
    });
    console.log('\n=== PLATFORM TILES ===');
    console.log('Count:', platformInfo.length);
    platformInfo.forEach((p, i) => {
      console.log(`  [${i}] text="${p.text}" imgSrc=${p.imgSrc} natural=${p.imgNw}x${p.imgNh} complete=${p.imgComplete} parent=${p.parentTag}.${p.parentClass}`);
    });

    // 3. Placeholders
    const placeholders = await page.evaluate(() => {
      const phs = document.querySelectorAll('.news-card__placeholder');
      return {
        count: phs.length,
        samples: Array.from(phs).slice(0, 3).map(p => ({
          outerHTML: p.outerHTML.substring(0, 600),
          text: p.textContent.trim(),
          bg: getComputedStyle(p).background?.substring(0, 150) || 'none',
        })),
      };
    });
    console.log('\n=== PLACEHOLDERS ===');
    console.log('Count:', placeholders.count);
    placeholders.samples.forEach((p, i) => {
      console.log(`  [${i}] text="${p.text}"`);
      console.log(`       bg: ${p.bg}`);
      console.log(`       html: ${p.outerHTML.substring(0, 200)}`);
    });

    // 4. Card images
    const cards = await page.evaluate(() => {
      const cards = document.querySelectorAll('.news-card');
      return {
        count: cards.length,
        withImage: Array.from(cards).filter(c => c.querySelector('.news-card__image')).length,
        withPlaceholder: Array.from(cards).filter(c => c.querySelector('.news-card__placeholder')).length,
        firstCardImg: cards[0]?.querySelector('.news-card__image img')?.getAttribute('src') || 'none',
        firstCardPlaceholder: cards[0]?.querySelector('.news-card__placeholder')?.outerHTML?.substring(0, 300) || 'none',
      };
    });
    console.log('\n=== CARDS ===');
    console.log('Total:', cards.count, '| With image:', cards.withImage, '| With placeholder:', cards.withPlaceholder);
    console.log('First card img src:', cards.firstCardImg);
    console.log('First card placeholder:', cards.firstCardPlaceholder);

    // 5. Screenshots
    await page.screenshot({ path: 'diag_filters.png', fullPage: false });
    await page.evaluate(() => window.scrollBy(0, 350));
    await new Promise(r => setTimeout(r, 300));
    await page.screenshot({ path: 'diag_cards.png', fullPage: false });
    console.log('\nScreenshots: diag_filters.png, diag_cards.png');

  } finally {
    await browser.close();
    server.close();
  }
})();
