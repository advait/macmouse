#!/usr/bin/env node
// Deterministic capture of stage.html: renderAt(t) per frame -> PNG frames.
// Usage: node capture.cjs OUT_DIR [fps] [t1,t2,... sample times instead of all frames]
// Needs playwright-core (NODE_PATH) and Chrome/Chromium (BROWSER_EXECUTABLE).
const fs = require('node:fs'), path = require('node:path'), { pathToFileURL } = require('node:url');
const { chromium } = require('playwright-core');
(async () => {
  const [out, fpsArg, samples] = process.argv.slice(2);
  const fps = Number(fpsArg || 60);
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: process.env.BROWSER_EXECUTABLE });
  const errors = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(pathToFileURL(path.join(__dirname, 'stage.html')).href);
    await page.evaluate(async () => { await document.fonts.ready; await window.ready; });
    const duration = await page.evaluate(() => window.duration);
    const times = samples ? samples.split(',').map(Number) : Array.from({ length: Math.ceil(duration * fps) }, (_, i) => i / fps);
    const stage = page.locator('#stage');
    for (let i = 0; i < times.length; i++) {
      await page.evaluate(t => window.renderAt(t), times[i]);
      await stage.screenshot({ path: path.join(out, samples ? `t${times[i].toFixed(2)}.png` : `${String(i).padStart(6, '0')}.png`) });
    }
    if (errors.length) throw Error('browser errors: ' + errors.join('; '));
    console.log(JSON.stringify({ duration, fps, frames: times.length }));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
