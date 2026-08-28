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
      const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png' };
      fs.readFile(filePath, (err, data) => {
        if (err) { res.writeHead(404); res.end('Not found'); return; }
        res.writeHead(200, { 'Content-Type': types[ext] || 'text/plain', 'Cache-Control': 'no-store' });
        res.end(data);
      });
    });
    server.listen(PORT, () => resolve(server));
  });
}

function parseRgb(str) {
  const s = (str || '').trim();
  const m = /rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/.exec(s);
  if (m) return [Number(m[1]), Number(m[2]), Number(m[3])];
  const c = /^color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)/.exec(s);
  if (c) return [round255(Number(c[1])), round255(Number(c[2])), round255(Number(c[3]))];
  return null;
}

function round255(v) {
  return Math.round(v * 255);
}

function relativeLuminance(rgb) {
  const [r, g, b] = rgb.map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function wcagContrast(a, b) {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

async function waitForCards(page) {
  await page.waitForSelector('.news-card', { timeout: 15000 });
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
    await page.setViewport({ width: 1280, height: 950 });
    await page.goto(`http://localhost:${PORT}`, { waitUntil: 'networkidle0' });
    await waitForCards(page);

    const surface = parseRgb(await page.evaluate(() => getComputedStyle(document.querySelector('.news-card')).backgroundColor));
    const border = parseRgb(await page.evaluate(() => getComputedStyle(document.querySelector('.news-card')).borderColor));
    console.log('=== TEST A: Vista NEWS (tinte azul EUROMARIO) ===');

    // Primer card NEWS (cualquiera no-rumor)
    const newsMeta = await page.evaluate(() => {
      const card = document.querySelector('.news-card:not([data-category="rumor"])');
      const content = card.querySelector('.news-card__content');
      const titleA = card.querySelector('.news-card__title a');
      return {
        category: card.getAttribute('data-category'),
        contentBg: getComputedStyle(content).backgroundColor,
        titleColor: getComputedStyle(titleA).color,
      };
    });
    console.log(`  card NEWS category=${newsMeta.category} contentBg=${newsMeta.contentBg} titleColor=${newsMeta.titleColor}`);
    const newsBg = parseRgb(newsMeta.contentBg);
    const newsTitle = parseRgb(newsMeta.titleColor);

    check('tinte aplicado (bg content != bg card)', !!newsBg && newsBg.join(',') !== surface.join(','), `content=${newsBg} card=${surface}`);
    const bMinusR_news = newsBg[2] - newsBg[0];
    check('NEWS es azul visible (8 <= b-r <= 30)', bMinusR_news >= 8 && bMinusR_news <= 30, `b-r=${bMinusR_news} (8% de #35b8ff ≈ 18)`);
    const deltaNews = Math.abs(newsBg[0]-surface[0]) + Math.abs(newsBg[1]-surface[1]) + Math.abs(newsBg[2]-surface[2]);
    check('tinte NEWS presente (delta total 15..40)', deltaNews >= 15 && deltaNews <= 40, `delta=${deltaNews} (8% ≈ 35)`);
    const contrastNews = wcagContrast(newsTitle, newsBg);
    check('contraste NEWS legible (>= 10:1)', contrastNews >= 10, `${contrastNews.toFixed(2)}:1`);

    console.log('  Screenshot -> test_card_tint_news.png');
    await page.screenshot({ path: 'test_card_tint_news.png', fullPage: false });

    console.log('\n=== TEST B: Vista RUMORS (tinte naranja) ===');
    await page.click('.header__nav-btn[data-section="rumors"]');
    await page.waitForSelector('.news-card[data-category="rumor"]', { timeout: 10000 });

    const rumorMeta = await page.evaluate(() => {
      const card = document.querySelector('.news-card[data-category="rumor"]');
      const content = card.querySelector('.news-card__content');
      const titleA = card.querySelector('.news-card__title a');
      return {
        count: document.querySelectorAll('.news-card[data-category="rumor"]').length,
        source: card.querySelector('.news-card__meta')?.textContent.trim().slice(0, 60) || '',
        contentBg: getComputedStyle(content).backgroundColor,
        titleColor: getComputedStyle(titleA).color,
      };
    });
    console.log(`  cards RUMORS visible=${rumorMeta.count} contentBg=${rumorMeta.contentBg} titleColor=${rumorMeta.titleColor}`);
    const rumorBg = parseRgb(rumorMeta.contentBg);
    const rumorTitle = parseRgb(rumorMeta.titleColor);

    check('hay cards RUMORS', rumorMeta.count >= 1, `count=${rumorMeta.count}`);
    const rMinusG_rumor = rumorBg[0] - rumorBg[1];
    check('RUMORS es naranja visible (2 <= r-g <= 12)', rMinusG_rumor >= 2 && rMinusG_rumor <= 12, `r-g=${rMinusG_rumor} (8% de #D29922 ≈ 4)`);
    const deltaRumor = Math.abs(rumorBg[0]-surface[0]) + Math.abs(rumorBg[1]-surface[1]) + Math.abs(rumorBg[2]-surface[2]);
    check('tinte RUMORS presente (delta total 15..40)', deltaRumor >= 15 && deltaRumor <= 40, `delta=${deltaRumor} (8% ≈ 27)`);
    const contrastRumor = wcagContrast(rumorTitle, rumorBg);
    check('contraste RUMORS legible (>= 10:1)', contrastRumor >= 10, `${contrastRumor.toFixed(2)}:1`);

    check('borde intacto (border-color == #26262B)', border.join(',') === '38,38,43', `border=${border}`);

    const hueCompare = bMinusR_news > 0 && rMinusG_rumor > 0;
    check('huesos opuestos: NEWS azul vs RUMORS naranja', hueCompare, `news b-r=${bMinusR_news}, rumor r-g=${rMinusG_rumor}`);

    console.log('  Screenshot -> test_card_tint_rumors.png');
    await page.screenshot({ path: 'test_card_tint_rumors.png' });

    console.log('\n=== TEST C: Tabs activos (NEWS azul EUROMARIO, RUMORS naranja) ===');
    const rumorTab = await page.evaluate(() => {
      const btn = document.querySelector('.header__nav-btn[data-section="rumors"]');
      const cs = getComputedStyle(btn);
      return { color: cs.color, bg: cs.backgroundColor, checked: btn.getAttribute('aria-checked') };
    });
    console.log(`  tab RUMORS activo color=${rumorTab.color} bg=${rumorTab.bg}`);
    const rt = parseRgb(rumorTab.color);
    check("tab RUMORS conserva naranja '#D29922' (rgb 210,153,34)", !!rt && rt[0] === 210 && rt[1] === 153 && rt[2] === 34, `color=${rt}`);

    await page.click('.header__nav-btn[data-section="news"]');
    await page.waitForFunction(() =>
      document.querySelector('.header__nav-btn[data-section="news"]').getAttribute('aria-checked') === 'true'
    );
    await new Promise((r) => setTimeout(r, 450)); // esperar a que termine la transición CSS del color
    const newsTab = await page.evaluate(() => {
      const btn = document.querySelector('.header__nav-btn[data-section="news"]');
      const cs = getComputedStyle(btn);
      return { color: cs.color, bg: cs.backgroundColor, checked: btn.getAttribute('aria-checked') };
    });
    console.log(`  tab NEWS activo color=${newsTab.color} bg=${newsTab.bg}`);
    const nt = parseRgb(newsTab.color);
    check("tab NEWS usa azul EUROMARIO '#35b8ff' (--accent, rgb 53,184,255)", !!nt && nt[0] === 53 && nt[1] === 184 && nt[2] === 255, `color=${nt}`);
    check('tab NEWS ya no usa verde lanzamiento (rgb 63,185,80)', !!nt && !(nt[0] === 63 && nt[1] === 185 && nt[2] === 80), `color=${nt}`);
  } catch (err) {
    console.error('ERROR:', err.message);
    allPassed = false;
  } finally {
    await browser.close();
    server.close();
  }

  console.log(`\n=== ${allPassed ? 'TODAS LAS VERIFICACIONES PASARON' : 'HUBO FALLOS'} ===`);
  process.exit(allPassed ? 0 : 1);
})();