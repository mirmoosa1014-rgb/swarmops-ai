// Optional local PNG export. Requires Playwright and installed Chrome; no network.
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
(async () => {
  const { chromium } = require('playwright');
  const directory = path.resolve(process.argv[2]);
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage({viewport: {width: 1100, height: 650}, deviceScaleFactor: 1});
    await page.route('http://**/*', route => route.abort());
    await page.route('https://**/*', route => route.abort());
    for (const name of (await fs.readdir(directory)).filter(x => x.endsWith('.svg'))) {
      await page.goto(pathToFileURL(path.join(directory,name)).href);
      await page.locator('svg').screenshot({path: path.join(directory,name.replace(/\.svg$/, '.png'))});
    }
    console.log('Exported five measured SVG charts to PNG.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
