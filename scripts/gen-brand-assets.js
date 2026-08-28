const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', 'frontend');
const ASSETS = path.join(FRONTEND, 'assets');
const FAVICON_SVG = fs.readFileSync(path.join(ASSETS, 'favicon.svg'), 'utf-8');
const ACCENT = '#35b8ff';

function svgDataUri(svg) {
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
}

async function renderSvg(browser, svg, size, outPath) {
  const page = await browser.newPage();
  await page.setViewport({ width: size, height: size, deviceScaleFactor: 1 });
  await page.setContent(`<!doctype html><html><head><style>html,body{margin:0;padding:0;background:#0A0A0B}</style></head><body><img id="i" width="${size}" height="${size}" src="${svgDataUri(svg)}" style="display:block"></body></html>`, { waitUntil: 'domcontentloaded' });
  const el = await page.$('#i');
  await el.screenshot({ path: outPath });
  await page.close();
  console.log(`  renderSvg -> ${path.relative(process.cwd(), outPath)} (${size}x${size})`);
}

async function renderBanner(browser, outPath) {
  const html = `<!doctype html><html><head>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo+Black&display=swap" rel="stylesheet">
<style>
  :root { color-scheme: dark; }
  body {
    margin: 0; width: 1200px; height: 630px; overflow: hidden;
    background: radial-gradient(900px 420px at 22% 6%, #1E2A38 0%, #0A0A0B 58%), #0A0A0B;
    color: #ECECEF;
    font-family: 'Archivo Black', 'Arial Black', Arial, sans-serif;
    display: flex; align-items: center; gap: 72px; padding: 0 84px; box-sizing: border-box;
  }
  .mark { width: 248px; height: 248px; flex: 0 0 auto; }
  .copy { flex: 0 0 auto; }
  .title { font-size: 92px; line-height: 1.02; letter-spacing: 0.005em; color: ${ACCENT}; margin: 0; white-space: nowrap; }
  .title .mar { color: #ECECEF; }
  .rule { width: 480px; height: 6px; border-radius: 3px; background: linear-gradient(90deg, ${ACCENT}, #0E2030); margin: 26px 0 22px; }
  .tagline { font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif; font-weight: 600; font-size: 26px; letter-spacing: 0.06em; color: #8B8E97; text-transform: uppercase; margin: 0; }
</style>
</head><body>
  <img class="mark" src="${svgDataUri(FAVICON_SVG)}" alt="">
  <div class="copy">
    <h1 class="title">Euro<span class="mar">Mario</span></h1>
    <div class="rule"></div>
    <p class="tagline">Gaming news &middot; Release radar &middot; Rumors</p>
  </div>
</body></html>`;
  const page = await browser.newPage();
  await page.setViewport({ width: 1200, height: 630, deviceScaleFactor: 1 });
  await page.setContent(html, { waitUntil: 'load' });
  try {
    await page.evaluate(async () => {
      if (document.fonts && document.fonts.ready) await document.fonts.ready;
    });
  } catch {}
  await new Promise(r => setTimeout(r, 400));
  await page.screenshot({ path: outPath });
  await page.close();
  console.log(`  renderBanner -> ${path.relative(process.cwd(), outPath)} (1200x630)`);
}

function buildIco(pngBuffer, size) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(1, 4);
  const entry = Buffer.alloc(16);
  entry[0] = size;
  entry[1] = size;
  entry[2] = 0;
  entry[3] = 0;
  entry.writeUInt16LE(1, 4);
  entry.writeUInt16LE(32, 6);
  entry.writeUInt32LE(pngBuffer.length, 8);
  entry.writeUInt32LE(22, 12);
  return Buffer.concat([header, entry, pngBuffer]);
}

(async () => {
  const browser = await puppeteer.launch({ headless: true });
  try {
    console.log('Generando favicon PNGs...');
    await renderSvg(browser, FAVICON_SVG, 16, path.join(ASSETS, 'favicon-16.png'));
    await renderSvg(browser, FAVICON_SVG, 32, path.join(ASSETS, 'favicon-32.png'));
    await renderSvg(browser, FAVICON_SVG, 180, path.join(ASSETS, 'apple-touch-icon.png'));

    console.log('Generando favicon.ico...');
    const png32 = fs.readFileSync(path.join(ASSETS, 'favicon-32.png'));
    fs.writeFileSync(path.join(FRONTEND, 'favicon.ico'), buildIco(png32, 32));
    console.log(`  buildIco -> frontend\\favicon.ico (${fs.statSync(path.join(FRONTEND, 'favicon.ico')).size} bytes)`);

    console.log('Generando OG banner 1200x630...');
    await renderBanner(browser, path.join(ASSETS, 'og-banner.png'));
  } finally {
    await browser.close();
  }
  console.log('=== ASSETS GENERADOS ===');
  process.exit(0);
})();