/**
 * gemini_stealth_login.js
 * Uses the exact stealth launcher from login_flow.js & core/stealth.js:
 * - ignoreDefaultArgs: ['--enable-automation']
 * - No --no-sandbox flag (prevents Google security flags)
 * - Injects navigator.webdriver = undefined
 * - Real desktop Chrome User-Agent
 * - Targets Profile 4 (Blazing Soul) or google_flow_profile
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
const readline = require('readline');

const PROJECT_DIR = 'C:\\Users\\ice\\Desktop\\youtube shorts project';
const targetProfile = process.argv[2] || 'flow_profile_4';
const profileDir = path.join(PROJECT_DIR, 'browser', targetProfile);

fs.mkdirSync(profileDir, { recursive: true });

// Clean stale locks
['SingletonLock', 'SingletonCookie', 'SingletonSocket', 'lockfile'].forEach(f => {
  try { const p = path.join(profileDir, f); if (fs.existsSync(p)) fs.unlinkSync(p); } catch (_) {}
});

function prompt(q) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise(resolve => rl.question(q, ans => { rl.close(); resolve(ans.trim()); }));
}

(async () => {
  console.log('================================================');
  console.log(`  STEALTH GEMINI LAUNCHER: ${targetProfile}`);
  console.log('================================================');
  console.log('>> Launching with exact stealth config from login_flow.js...');
  console.log('>> No --enable-automation flag');
  console.log('>> No --no-sandbox flag');
  console.log('>> Opening https://gemini.google.com/app ...\n');

  const context = await chromium.launchPersistentContext(profileDir, {
    channel: 'chrome',
    headless: false,
    slowMo: 0,
    args: [
      '--disable-blink-features=AutomationControlled',
      '--start-maximized',
      '--disable-infobars',
    ],
    ignoreDefaultArgs: ['--enable-automation'],
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    viewport: null,
  });

  const page = context.pages()[0] || await context.newPage();
  
  // Inject stealth script
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = {
      runtime: { onInstalled: { addListener: () => {} } },
      loadTimes: () => {},
      csi: () => {},
      app: {},
    };
    delete window.__playwright;
    delete window.__pw_manual;
  });

  await page.goto('https://gemini.google.com/app', { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {});

  console.log('>> Browser is open!');
  console.log('>> If needed, sign into Google (e.g. blazingsoul451@gmail.com).');
  console.log('>> When you see the Gemini prompt box and account avatar, press ENTER here.\n');

  await prompt('>> Press ENTER when you are signed in and ready: ');

  console.log('\nChecking session status...');
  const avatar = await page.$('a[aria-label*="Google Account" i], button[aria-label*="Google Account" i]');
  const aria = avatar ? await avatar.getAttribute('aria-label') : 'None';
  console.log(`Detected Account: ${aria}`);

  await page.screenshot({ path: path.join(PROJECT_DIR, 'whop-editor', 'data', 'analysis', `${targetProfile}_gemini_verified.png`) });
  console.log(`Saved screenshot to whop-editor/data/analysis/${targetProfile}_gemini_verified.png`);

  await context.close();
  console.log('\n[OK] Session saved successfully!');
  process.exit(0);
})();
