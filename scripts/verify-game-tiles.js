const puppeteer = require('puppeteer');
const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const FRONTEND_DIR = path.join(__dirname, '..', 'frontend');
const PORT = 8771;

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

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 900 });
    await page.goto('http://localhost:' + PORT, { waitUntil: 'networkidle0' });
    await new Promise(r => setTimeout(r, 1000));

    // Check game tiles
    const gameTiles = await page.evaluate(() => {
      const tiles = document.querySelectorAll('#game-tiles .game-tile');
      return Array.from(tiles).filter(t => t.dataset.game).map(t => ({
        game: t.dataset.game,
        text: t.textContent.trim(),
        hasImg: !!t.querySelector('img'),
        hasInitial: !!t.querySelector('.game-tile__initial'),
      }));
    });

    console.log('=== Game tiles (' + gameTiles.length + ') ===');
    gameTiles.forEach(t => {
      const logo = t.hasImg ? 'SVG' : (t.hasInitial ? 'inicial' : '???');
      console.log('  ' + t.game.padEnd(22) + logo);
    });

    // Check which games from news are in tiles
    const news = require('./frontend/data/news.json');
    const newsGames = [...new Set(news.news.map(n => n.game).filter(Boolean))].sort();
    const tileGames = gameTiles.map(t => t.game);

    console.log('\n=== Coverage ===');
    newsGames.forEach(g => {
      const found = tileGames.includes(g);
      console.log('  ' + (found ? 'OK' : 'MISSING') + '  ' + g);
    });

    await page.screenshot({ path: 'diag_game_tiles_final.png', fullPage: false });

    await browser.close();
    server.close();
  } catch (e) {
    console.error(e);
    await browser.close();
    server.close();
    process.exit(1);
  }
})();
