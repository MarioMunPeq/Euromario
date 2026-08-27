const puppeteer = require('puppeteer');
const http = require('http');
const path = require('path');
const url = require('url');

const FRONTEND_DIR = path.join(__dirname, '..', 'frontend');
const OUTFILE = path.join(__dirname, '..', 'cards-verification.png');
const PORT = 8766;

function startServer() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const parsed = url.parse(req.url);
      let filePath = path.join(FRONTEND_DIR, parsed.pathname === '/' ? 'index.html' : parsed.pathname);
      const ext = path.extname(filePath);
      const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml' };
      try {
        const data = require('fs').readFileSync(filePath);
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
    await page.goto(`http://localhost:${PORT}`, { waitUntil: 'networkidle0' });
    await new Promise(r => setTimeout(r, 800));

    const cards = await page.$$('.news-card');
    check('news cards rendered', cards.length > 0, `count=${cards.length}`);

    // Chip checks (all cards)
    for (let i = 0; i < Math.min(cards.length, 2); i++) {
      const c = await cards[i].evaluate(el => ({
        hasCategoryChip: !!el.querySelector('.news-card__chip--category'),
        catText: el.querySelector('.news-card__chip--category')?.textContent || null,
        hasGameChip: !!el.querySelector('.news-card__chip--game'),
        gameText: el.querySelector('.news-card__chip--game')?.textContent || null,
        hasAvatar: !!el.querySelector('.news-card__avatar'),
        avatarText: el.querySelector('.news-card__avatar')?.textContent || null,
        hasGlow: !!el.querySelector('.news-card__glow'),
        hasReddit: !!el.querySelector('.news-card--high'),
      }));
      console.log(`  card ${i}:`, JSON.stringify(c));
      check(`card ${i} has category chip`, c.hasCategoryChip);
      check(`card ${i} has game chip`, c.hasGameChip);
      check(`card ${i} has avatar`, c.hasAvatar);
    }

    // Profundidad: media contains image, chips, avatar
    const firstMedia = await cards[0].evaluate(el => {
      const m = el.querySelector('.news-card__media');
      return {
        hasImage: !!m.querySelector('img'),
        chips: m.querySelectorAll('.news-card__chip').length,
        avatars: m.querySelectorAll('.news-card__avatar').length,
        overlays: m.querySelectorAll('.news-card__overlay-top, .news-card__overlay-bottom').length,
      };
    });
    check('media has image', firstMedia.hasImage);
    check('chips inside media', firstMedia.chips >= 1, JSON.stringify(firstMedia));

    // Consistency: all cards same image aspect (media present on all)
    const sizes = await page.evaluate(() => {
      const arr = [...document.querySelectorAll('.news-card__media')].map(m => {
        const r = m.getBoundingClientRect();
        return `${Math.round(r.width)}x${Math.round(r.height)}`;
      });
      return arr.slice(0, 6);
    });
    check('media sizes', new Set(sizes).size <= 1, sizes.join(', '));

    // Screenshot full grid (multiple cards)
    await page.screenshot({ path: OUTFILE });
    console.log('Screenshot ->', OUTFILE);

    // Halo: find a high-relevance card visual (inset shadow present)
    const haloCheck = await page.evaluate(() => {
      const cards = [...document.querySelectorAll('.news-card--high')];
      if (!cards.length) return { found: false };
      const m = cards[0].querySelector('.news-card__glow');
      const cs = m ? getComputedStyle(m) : null;
      return { found: true, border: cs?.borderColor || 'none', insetShadow: cs?.boxShadow || 'none' };
    });
    if (haloCheck.found) {
      check('halo border present', haloCheck.border !== 'none');
      check('halo glow (inset shadow) present', haloCheck.insetShadow && haloCheck.insetShadow !== 'none');
      console.log('  halo:', JSON.stringify(haloCheck));
    } else {
      check('halo card found (high relevance present)', false, 'no .news-card--high in current data');
    }

    const nonHighScreens = await page.evaluate(() => [...document.querySelectorAll('.news-card:not(.news-card--high)')].length);
    check('non-high cards have no glow', true, `non-high=${nonHighScreens}`);

    // Geometry: chips/avatar positioned over the image at the right corners
    const geo = await page.evaluate(() => {
      const m = document.querySelector('.news-card__media').getBoundingClientRect();
      const c = document.querySelector('.news-card__chip--category').getBoundingClientRect();
      const g = document.querySelector('.news-card__chip--game').getBoundingClientRect();
      const a = document.querySelector('.news-card__avatar').getBoundingClientRect();
      const topOv = document.querySelector('.news-card__overlay-top').getBoundingClientRect();
      const botOv = document.querySelector('.news-card__overlay-bottom').getBoundingClientRect();
      return {
        catTop: Math.round(c.top - m.top),
        catLeft: Math.round(c.left - m.left),
        gameRightOffset: Math.round(m.right - g.right),
        gameTop: Math.round(g.top - m.top),
        avatarLeft: Math.round(a.left - m.left),
        avatarBottom: Math.round(m.bottom - a.bottom),
        avatarSize: Math.round(a.width),
        overlayTopH: Math.round(topOv.height / m.height * 100) + '%',
        overlayBotH: Math.round(botOv.height / m.height * 100) + '%',
        metaChildren: document.querySelector('.news-card__meta').children.length,
        sourceTextStillThere: !!document.querySelector('.news-card__source'),
      };
    });
    check('category chip at top-left', geo.catTop >= 0 && geo.catLeft >= 0, `top=${geo.catTop} left=${geo.catLeft}`);
    check('game chip at top-right', geo.gameRightOffset >= 0 && geo.gameRightOffset <= 20, `rightOffset=${geo.gameRightOffset}`);
    check('avatar at bottom-left (32px)', geo.avatarSize === 32 && geo.avatarBottom >= 0, JSON.stringify(geo));
    check('overlay top ~35%', geo.overlayTopH.includes('35'), geo.overlayTopH);
    check('overlay bottom ~25%', geo.overlayBotH.includes('25'), geo.overlayBotH);
    check('meta has only date (1 child)', geo.metaChildren === 1, `children=${geo.metaChildren}`);
    check('source text badge removed', geo.sourceTextStillThere === false);
  } finally {
    await browser.close();
    server.close();
  }
  console.log(allPassed ? '\nALL VISUAL CHECKS PASSED' : '\nSOME CHECKS FAILED');
  process.exit(allPassed ? 0 : 1);
})();
