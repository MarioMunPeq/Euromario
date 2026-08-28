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

async function diagnose(page, width) {
  return page.evaluate(() => {
    const nav = document.querySelector('.header__nav');
    const btns = [...document.querySelectorAll('.header__nav-btn')];
    const brand = document.querySelector('.header__brand');
    const inner = document.querySelector('.header__inner');
    const cs = (el) => el ? window.getComputedStyle(el) : null;
    const navCS = cs(nav);
    const innerCS = cs(inner);
    const brandCS = cs(brand);
    const rect = nav ? nav.getBoundingClientRect() : null;
    const innerRect = inner ? inner.getBoundingClientRect() : null;
    return {
      navExists: !!nav,
      navButtonCount: btns.length,
      navDisplay: navCS ? navCS.display : null,
      navVisibility: navCS ? navCS.visibility : null,
      navOverflow: nav ? navCS.overflow : null,
      navRect: rect ? { width: Math.round(rect.width), height: Math.round(rect.height) } : null,
      innerRect: innerRect ? { width: Math.round(innerRect.width), height: Math.round(innerRect.height) } : null,
      navIsRenderable: !!rect && rect.width > 0 && rect.height > 0,
      brandRect: brand ? { width: Math.round(brand.getBoundingClientRect().width) } : null,
    };
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
    for (const width of [375, 480, 768]) {
      const page = await browser.newPage();
      await page.setViewport({ width, height: 800 });
      await page.goto(`http://localhost:${PORT}`, { waitUntil: 'networkidle0' });
      await new Promise(r => setTimeout(r, 600));
      const d = await diagnose(page, width);
      console.log(`\n=== VIEWPORT ${width}px ===`);
      console.log(' ', JSON.stringify(d));
      check(`${width}: nav existe en DOM`, d.navExists);
      check(`${width}: 2 botones en DOM`, d.navButtonCount === 2);
      check(`${width}: nav display != none`, d.navDisplay !== 'none', `display=${d.navDisplay}`);
      check(`${width}: nav renderizable (w/h > 0)`, d.navIsRenderable && d.navDisplay !== 'none', JSON.stringify(d.navRect));
      await page.screenshot({ path: path.join(__dirname, '..', `test_movil_${width}.png`) });
      await page.close();
    }
  } finally {
    await browser.close();
    server.close();
  }
  console.log(allPassed ? '\n=== NAV VISIBLE EN TODOS LOS VIEWPORT ===' : '\n=== NAV NO VISIBLE EN ALGUN VIEWPORT ===');
  process.exit(allPassed ? 0 : 1);
})();