const puppeteer = require('puppeteer');
const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const FRONTEND_DIR = path.join(__dirname, '..', 'frontend');
const PORT = 8767;

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
    await new Promise(r => setTimeout(r, 1000));

    // ============================================================
    // TEST A: Simplified topbar (no search, no magnifier)
    // ============================================================
    console.log('\n=== TEST A: Topbar simplificada (sin buscador ni lupa) ===');
    const topbar = await page.evaluate(() => {
      const header = document.querySelector('.header__inner');
      const brand = document.querySelector('.header__brand');
      const nav = document.querySelector('.header__nav');
      const navBtns = [...document.querySelectorAll('.header__nav-btn')];
      return {
        headerExists: !!header,
        brandExists: !!brand,
        brandLogo: !!brand?.querySelector('.header__logo'),
        navExists: !!nav,
        navBtnCount: navBtns.length,
        navLabels: navBtns.map(b => b.textContent.trim()),
        hasSearchEl: !!document.querySelector('.header__search'),
        hasSearchInput: !!document.getElementById('search'),
        hasSearchTrigger: !!document.querySelector('.header__search-trigger'),
        hasSearchField: !!document.querySelector('.header__search-field'),
        hasSearchIcon: !!document.querySelector('.header__search-icon-img'),
        searchSvgRequested: false,
        headerHtmlHasLupa: header?.innerHTML.includes('lupa') || header?.innerHTML.includes('search'),
        brandOrder: header ? header.children[0]?.className : null,
        navOrder: header ? header.children[1]?.className : null,
      };
    });
    check('topbar existe', topbar.headerExists);
    check('logo a la izquierda (primer hijo)', topbar.brandExists && String(topbar.brandOrder).includes('brand'));
    check('logo con imagen', topbar.brandLogo);
    check('nav presente', topbar.navExists);
    check('2 botones NEWS/RUMORS', topbar.navBtnCount === 2, `labels=${JSON.stringify(topbar.navLabels)}`);
    check('nav a la derecha (segundo hijo)', String(topbar.navOrder).includes('nav'));
    check('sin .header__search', !topbar.hasSearchEl);
    check('sin input #search', !topbar.hasSearchInput);
    check('sin trigger de lupa', !topbar.hasSearchTrigger);
    check('sin campo de búsqueda', !topbar.hasSearchField);
    check('sin icono de lupa', !topbar.hasSearchIcon);

    // Verificar que ninguna petición a search.svg ocurre
    page.removeAllListeners('request');
    const svgRequested = [];
    page.on('request', req => { if (req.url().includes('search.svg')) svgRequested.push(req.url()); });
    await page.reload({ waitUntil: 'networkidle0' });
    await new Promise(r => setTimeout(r, 800));
    check('no se solicita search.svg', svgRequested.length === 0, `requests=${svgRequested.length}`);
    await page.screenshot({ path: path.join(__dirname, '..', 'test_topbar_simplificada.png') });
    console.log('  Screenshot -> test_topbar_simplificada.png');

    // ============================================================
    // TEST B: Real images showing (key 'image' vs 'image_url')
    // ============================================================
    console.log('\n=== TEST B: Imágenes reales en las cards ===');
    const raw = require('fs').readFileSync(path.join(FRONTEND_DIR, 'data/news.json'));
    const data = JSON.parse(raw.toString('utf-8'));
    const dataWithImage = data.news.filter(i => i.image).length;
    const dataWithoutImage = data.news.length - dataWithImage;
    const imgs = await page.evaluate(async () => {
      const cards = [...document.querySelectorAll('.news-card')];
      const result = {
        cardCount: cards.length,
        withImage: 0,
        withPlaceholder: 0,
        brokenImages: 0,
        imageSrcs: [],
        firstCardHasImage: !!cards[0]?.querySelector('.news-card__image'),
        firstImageSrc: cards[0]?.querySelector('.news-card__image')?.getAttribute('src') || null,
      };
      for (const card of cards) {
        const img = card.querySelector('.news-card__image');
        if (img) {
          result.withImage++;
          result.imageSrcs.push(img.getAttribute('src'));
        } else {
          result.withPlaceholder++;
        }
      }
      // Check a sample of images actually load (naturalWidth > 0)
      const sample = cards.slice(0, 6).map(c => c.querySelector('.news-card__image'));
      const loadStates = await Promise.all(sample.map(async (img) => {
        if (!img) return { loaded: false, placeholder: true };
        if (img.complete && img.naturalWidth > 0) return { loaded: true, width: img.naturalWidth };
        if (img.complete) return { loaded: false, broken: true };
        return new Promise((resolve) => {
          img.addEventListener('load', () => resolve({ loaded: true, width: img.naturalWidth }), { once: true });
          img.addEventListener('error', () => resolve({ loaded: false, broken: true }), { once: true });
        });
      }));
      result.sampleLoadStates = loadStates;
      result.sampleLoaded = loadStates.filter(s => s.loaded).length;
      return result;
    });
    check('cards renderizadas', imgs.cardCount > 0, `count=${imgs.cardCount}`);
    check('primera card usa <img> real (no placeholder)', imgs.firstCardHasImage === true, `src=${imgs.firstImageSrc || 'NONE'}`);
    check('todas las card con imagen en datos usan <img>', imgs.withImage === dataWithImage, `render=${imgs.withImage} datos=${dataWithImage}`);
    check('placeholders solo en items sin imagen', imgs.withPlaceholder === dataWithoutImage, `render=${imgs.withPlaceholder} datos=${dataWithoutImage}`);
    const broken = imgs.sampleLoadStates.filter(s => s.broken).length;
    check('muestra de imágenes cargadas correctamente', imgs.sampleLoaded >= 4 && broken === 0, `cargadas=${imgs.sampleLoaded}/${imgs.sampleLoadStates.length} rotas=${broken}`);
    await page.screenshot({ path: path.join(__dirname, '..', 'test_imagenes_reales.png') });
    console.log('  Screenshot -> test_imagenes_reales.png');

    // ============================================================
    // TEST C: Sin footer ni contador/updated en el header
    // ============================================================
    console.log('\n=== TEST C: Sin footer ni contador/"actualizado hace X" ===');
    const noFooter = await page.evaluate(() => {
      const header = document.querySelector('.header');
      const headerText = header ? header.innerText : '';
      return {
        hasFooter: !!document.querySelector('.footer'),
        footerLinks: document.querySelectorAll('.footer__link').length,
        hasHeaderCount: !!document.getElementById('header-count'),
        hasHeaderUpdated: !!document.getElementById('header-updated'),
        headerCounter: /\d+\s*(news|noticia)/i.test(headerText),
        headerUpdatedAgo: /\b(ago|hace)\b/i.test(headerText),
        headerText: headerText.replace(/\s+/g, ' ').trim(),
      };
    });
    check('sin .footer', !noFooter.hasFooter);
    check('sin enlace de versión en footer', noFooter.footerLinks === 0);
    check('sin #header-count', !noFooter.hasHeaderCount);
    check('sin #header-updated', !noFooter.hasHeaderUpdated);
    check('header sin contador de noticias', !noFooter.headerCounter);
    check('header sin "actualizado hace X"', !noFooter.headerUpdatedAgo);
    console.log(`  header="${noFooter.headerText}"`);

    // ============================================================
    // TEST D: Favicon + Open Graph + Twitter Card
    // ============================================================
    console.log('\n=== TEST D: Favicon, Open Graph y Twitter Card ===');
    const head = await page.evaluate(async () => {
      const q = (sel, attr) => {
        const el = document.querySelector(sel);
        return el ? el.getAttribute(attr) : null;
      };
      const meta = (prop) => q(`meta[property="${prop}"], meta[name="${prop}"]`, 'content');
      const status = async (href) => {
        try {
          const r = await fetch(href, { method: 'HEAD' });
          return r.status;
        } catch { return -1; }
      };
      return {
        icons: [...document.querySelectorAll('link[rel="icon"], link[rel="shortcut icon"], link[rel="apple-touch-icon"]')].map(l => l.getAttribute('href')),
        ogTitle: meta('og:title'),
        ogDesc: meta('og:description'),
        ogUrl: meta('og:url'),
        ogImage: meta('og:image'),
        ogType: meta('og:type'),
        twitterCard: meta('twitter:card'),
        description: meta('description'),
        iconStatus: await status('assets/favicon.svg'),
        pngStatus: await status('assets/favicon-32.png'),
        bannerStatus: await status('assets/og-banner.png'),
        icoStatus: await status('favicon.ico'),
      };
    });
    check('favicon svg declarado', head.icons.some(h => h.includes('favicon.svg')), `icons=${JSON.stringify(head.icons)}`);
    check('favicon png 32 + ico cubiertos', head.icons.some(h => h.includes('favicon-32')) && head.icons.some(h => h === 'favicon.ico'));
    check('apple-touch-icon presente', head.icons.some(h => h.includes('apple-touch-icon')));
    check('assets favicon.svg responde 200', head.iconStatus === 200, `status=${head.iconStatus}`);
    check('assets favicon-32.png responde 200', head.pngStatus === 200, `status=${head.pngStatus}`);
    check('favicon.ico responde 200', head.icoStatus === 200, `status=${head.icoStatus}`);
    check('og:title presente', !!head.ogTitle, `title=${head.ogTitle}`);
    check('og:description presente', !!head.ogDesc);
    check('og:url es URL canónica', head.ogUrl === 'https://mariomunpeq.github.io/Euromario/', `url=${head.ogUrl}`);
    check('og:image presente', head.ogImage && head.ogImage.endsWith('/assets/og-banner.png'), `image=${head.ogImage}`);
    check('og:type website', head.ogType === 'website', `type=${head.ogType}`);
    check('og-banner.png responde 200', head.bannerStatus === 200, `status=${head.bannerStatus}`);
    check('twitter:card summary_large_image', head.twitterCard === 'summary_large_image', `card=${head.twitterCard}`);
    check('meta description presente', !!head.description);

  } finally {
    await browser.close();
    server.close();
  }
  console.log(allPassed ? '\n=== TODAS LAS VERIFICACIONES PASARON ===' : '\n=== HAY FALLOS ===');
  process.exit(allPassed ? 0 : 1);
})();