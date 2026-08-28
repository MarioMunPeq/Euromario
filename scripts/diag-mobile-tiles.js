const puppeteer = require('puppeteer');
const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const FRONTEND_DIR = path.join(__dirname, '..', 'frontend');
const PORT = 8768;

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

const WIDTHS = [375, 412, 540, 768, 1024];

(async () => {
  const server = await startServer();
  const browser = await puppeteer.launch({ headless: true });
  try {
    const page = await browser.newPage();
    for (const w of WIDTHS) {
      await page.setViewport({ width: w, height: 812 });
      await page.goto(`http://localhost:${PORT}/?v=${Date.now()}`, { waitUntil: 'networkidle0' });
      await new Promise(r => setTimeout(r, 900));

      const info = await page.evaluate(() => {
        const measure = (sel) => {
          const el = document.querySelector(sel);
          if (!el) return null;
          const er = el.getBoundingClientRect();
          const tiles = [...el.querySelectorAll('.game-tile')].map(t => {
            const r = t.getBoundingClientRect();
            return { left: +r.left.toFixed(1), right: +r.right.toFixed(1), width: +r.width.toFixed(1), visibleRight: r.right <= er.right + 0.5, visibleLeft: r.left >= er.left - 0.5 };
          });
          return {
            clientWidth: el.clientWidth,
            scrollWidth: el.scrollWidth,
            overflowX: getComputedStyle(el).overflowX,
            flexWrap: getComputedStyle(el).flexWrap,
            containerRight: +er.right.toFixed(1),
            tileCount: tiles.length,
            fullyVisible: tiles.filter(t => t.visibleRight && t.visibleLeft).length,
            clippedRight: tiles.filter(t => !t.visibleRight).map(t => ({ right: t.right, width: t.width })),
            minTileRight: tiles.length ? Math.min(...tiles.map(t => t.right)) : null,
            maxTileRight: tiles.length ? Math.max(...tiles.map(t => t.right)) : null,
          };
        };

        const cyberpunk = [...document.querySelectorAll('.game-tile')].find(t => t.textContent.includes('Cyberpunk 2077'));
        const cp = cyberpunk ? (() => {
          const tr = cyberpunk.getBoundingClientRect();
          const name = cyberpunk.querySelector('.game-tile__name');
          const nr = name ? name.getBoundingClientRect() : null;
          return {
            tileWidth: +tr.width.toFixed(1),
            nameWidth: nr ? +nr.width.toFixed(1) : 0,
            nameOverflowsTile: nr ? nr.width > tr.width : false,
            nameWs: name ? getComputedStyle(name).whiteSpace : null,
            nameMaxW: name ? getComputedStyle(name).maxWidth : null,
            nameText: name ? name.textContent.trim() : null,
            rect: { left: +tr.left.toFixed(1), right: +tr.right.toFixed(1) },
          };
        })() : null;

        return {
          vw: window.innerWidth,
          docScrollWidth: document.documentElement.scrollWidth,
          docClientWidth: document.documentElement.clientWidth,
          platforms: measure('#filter-platforms'),
          games: measure('#filter-games'),
          cyberpunk: cp,
        };
      });

      console.log(`\n=== VIEWPORT ${w}px ===`);
      console.log(`  document overflow: scrollWidth=${info.docScrollWidth} vs clientWidth=${info.docClientWidth} ${info.docScrollWidth > info.docClientWidth ? '=> ¡OVERFLOW HORIZONTAL!' : '=> ok'}`);
      for (const key of ['platforms', 'games']) {
        const m = info[key];
        console.log(`  #${key === 'platforms' ? 'filter-platforms' : 'filter-games'}:`);
        if (!m) { console.log('    (no encontrado)'); continue; }
        console.log(`    container clientWidth=${m.clientWidth} scrollWidth=${m.scrollWidth} overflowX=${m.overflowX} flexWrap=${m.flexWrap}`);
        console.log(`    tiles=${m.tileCount} fullyVisible=${m.fullyVisible} clippedAtRight=${m.clippedRight.length ? JSON.stringify(m.clippedRight.slice(0,3)) : 0} maxTileRight=${m.maxTileRight} containerRight=${m.containerRight}`);
      }
      console.log(`  Cyberpunk 2077: ${JSON.stringify(info.cyberpunk)}`);
      await page.screenshot({ path: path.join(__dirname, '..', `test_mobile_tiles_${w}.png`), fullPage: false });
    }
  } finally {
    await browser.close();
    server.close();
  }
  console.log('\n=== DIAGNÓSTICO COMPLETO ===');
  process.exit(0);
})();