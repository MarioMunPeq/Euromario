const puppeteer = require('puppeteer');
const http = require('http');
const path = require('path');
const url = require('url');
const fs = require('fs');

const FRONTEND_DIR = path.join(__dirname, '..', 'frontend');
const OUTFILE = path.join(__dirname, '..', 'cards-avatar-verification.png');
const PORT = 8768;

function startServer() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const parsed = url.parse(req.url);
      let filePath = path.join(FRONTEND_DIR, parsed.pathname === '/' ? 'index.html' : parsed.pathname);
      const ext = path.extname(filePath);
      const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml' };
      try {
        const data = fs.readFileSync(filePath);
        res.writeHead(200, { 'Content-Type': types[ext] || 'application/octet-stream' });
        res.end(data);
      } catch (e) {
        res.writeHead(404);
        res.end('Not found');
      }
    });
    server.listen(PORT, () => resolve(server));
  });
}

function svgImage(bg, label, fg) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="${bg}"/><text x="50%" y="50%" font-family="Arial" font-size="40" fill="${fg}" text-anchor="middle" dominant-baseline="middle">${label}</text></svg>`;
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
}

const now = new Date().toISOString();

const curated = {
  generated_at: now,
  total: 3,
  news: [
    {
      id: 'aaaa000000000001', title: 'GTA 6: fecha de lanzamiento confirmada (Polygon, alta relevancia)',
      summary: 'Polygon confirma la ventana de lanzamiento de GTA 6 con nuevos detalles.',
      url: 'https://www.polygon.com/gta-6', 
      source: { name: 'Polygon', type: 'media', subreddit: null },
      game: 'Grand Theft Auto', language: 'en', published_at: now,
      relevance: 5, category: 'lanzamiento', image_url: svgImage('#1e2a38', 'POLYGON', '#E8ECF0'),
    },
    {
      id: 'bbbb000000000002', title: 'r/pcgaming: filtrado el próximo juego de Valve (Reddit, alta)',
      summary: 'Comuidad detecta un registro en Steam que apunta a un nuevo juego de Valve.',
      url: 'https://www.reddit.com/r/pcgaming/comments/valve',
      source: { name: 'r/pcgaming', type: 'reddit', subreddit: 'pcgaming' },
      game: 'Half-Life', language: 'en', published_at: now,
      relevance: 5, category: 'rumor', image_url: svgImage('#3a2430', 'REDDIT', '#FF7A45'),
    },
    {
      id: 'cccc000000000003', title: 'Steam: parche 1.1 de Grand Theft Auto ya disponible',
      summary: 'El parche corrige errores de rendimiento en PC y PlayStation.',
      url: 'https://store.steampowered.com/news/app/271590',
      source: { name: 'Steam · Grand Theft Auto', type: 'steam', subreddit: null },
      game: 'Grand Theft Auto', language: 'es', published_at: now,
      relevance: 4, category: 'actualizacion', image_url: svgImage('#11263a', 'STEAM', '#a5d8ff'),
    },
  ],
};

(async () => {
  const server = await startServer();
  const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox'] });
  let allPassed = true;
  function check(label, condition, info) {
    const status = condition ? 'PASS' : 'FAIL';
    if (!condition) allPassed = false;
    console.log(`  [${status}] ${label}${info ? ' — ' + info : ''}`);
  }
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 1000 });
    await page.setRequestInterception(true);
    page.on('request', req => {
      if (req.url().includes('news.json')) {
        req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(curated) });
      } else {
        req.continue();
      }
    });
    await page.goto(`http://localhost:${PORT}`, { waitUntil: 'networkidle0' });
    await new Promise(r => setTimeout(r, 800));

    const cards = await page.$$('.news-card');
    check('3 cards rendered', cards.length === 3, `count=${cards.length}`);

    const info = await page.evaluate(() => {
      return [...document.querySelectorAll('.news-card')].map(el => {
        const avatar = el.querySelector('.news-card__avatar');
        const media = el.querySelector('.news-card__media').getBoundingClientRect();
        const a = avatar.getBoundingClientRect();
        return {
          type: el.querySelector('.news-card__chip--game')?.textContent || '',
          avatarText: avatar.textContent,
          avatarBg: getComputedStyle(avatar).backgroundColor,
          avatarColor: getComputedStyle(avatar).color,
          avatarW: Math.round(a.width),
          overImage: a.top >= media.top && a.bottom <= media.bottom && a.left >= media.left && a.right <= media.right,
          hasImage: !!el.querySelector('.news-card__image'),
          hasGlow: !!el.querySelector('.news-card__glow'),
          glowBorder: el.querySelector('.news-card__glow') ? getComputedStyle(el.querySelector('.news-card__glow')).borderColor : 'none',
        };
      });
    });

    info.forEach((c, i) => console.log(`  card ${i}:`, JSON.stringify(c)));

    // Reddit avatar: orange + white (brand identity)
    const reddit = info[1];
    check('reddit card exists', !!reddit && reddit.hasImage);
    check('reddit avatar over image', !!(reddit && reddit.overImage));
    check('reddit avatar orange', !!(reddit && reddit.avatarBg === 'rgb(255, 69, 0)'), reddit && reddit.avatarBg);
    check('reddit initials white', !!(reddit && reddit.avatarColor === 'rgb(255, 255, 255)'), reddit && reddit.avatarColor);
    check('reddit initials visible (non-empty)', !!(reddit && reddit.avatarText.trim().length > 0), reddit && `"${reddit.avatarText}"`);
    check('reddit halo present (high relevance + rumor color)', !!(reddit && reddit.hasGlow), reddit && reddit.glowBorder);

    // Steam avatar: blue + navy text (legible 9.17:1)
    const steam = info[2];
    check('steam card exists', !!steam && steam.hasImage);
    check('steam avatar over image', !!(steam && steam.overImage));
    check('steam avatar blue', !!(steam && steam.avatarBg === 'rgb(102, 192, 244)'), steam && steam.avatarBg);
    check('steam initials navy (dark for contrast)', !!(steam && steam.avatarColor === 'rgb(10, 14, 20)'), steam && steam.avatarColor);
    check('steam initials visible', !!(steam && steam.avatarText.trim().length > 0), steam && `"${steam.avatarText}"`);
    check('steam halo present (relevance 4)', !!(steam && steam.hasGlow), steam && steam.glowBorder);

    // Media (Polygon) baseline
    const media = info[0];
    check('media avatar navy surface', !!(media && media.avatarBg === 'rgb(30, 42, 56)'), media && media.avatarBg);
    check('media initials white', !!(media && media.avatarColor === 'rgb(255, 255, 255)'), media && media.avatarColor);

    await page.screenshot({ path: OUTFILE });
    console.log('Screenshot ->', OUTFILE);
  } finally {
    await browser.close();
    server.close();
  }
  console.log(allPassed ? '\nALL AVATAR CHECKS PASSED' : '\nSOME CHECKS FAILED');
  process.exit(allPassed ? 0 : 1);
})();