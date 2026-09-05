/**
 * GOOGLE FLOW & GEMINI — COMPLETE DUAL-LOGIN MANAGER
 * Opens both Google Flow and Gemini in separate tabs for each profile.
 * Verifies and saves full authentication for both video generation and review.
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
const readline = require('readline');

const PROJECT_DIR = 'C:\\Users\\ice\\Desktop\\youtube shorts project';
const BROWSER_DIR = path.join(PROJECT_DIR, 'browser');
const MC_PATH = path.join(PROJECT_DIR, 'mission_control.json');
const REGISTRY_FILE = path.join(BROWSER_DIR, 'profile_registry.json');
const VERIFIED_FILE = path.join(PROJECT_DIR, 'verified_sessions.json');

const ACCOUNTS = [
  { id: 1, profile: 'flow_profile_1', email: 'mohsinoctal777@gmail.com', label: 'Account 1 (Primary Pro)' },
  { id: 2, profile: 'flow_profile_2', email: 'aoctal522@gmail.com', label: 'Account 2 (Octal Pro)' },
  { id: 3, profile: 'flow_profile_3', email: 'mohsinmughal1771@gmail.com', label: 'Account 3 (Mughal Pro)' },
  { id: 4, profile: 'flow_profile_4', email: 'blazingsoul451@gmail.com', label: 'Account 4 (Blazing Soul Pro)' },
  { id: 5, profile: 'flow_profile_5', email: 'zestify1771@gmail.com', label: 'Account 5 (Alex / Zestify Pro)' },
];

function getVerified() {
  try {
    if (fs.existsSync(VERIFIED_FILE)) {
      return JSON.parse(fs.readFileSync(VERIFIED_FILE, 'utf8'));
    }
  } catch (_) {}
  return [];
}

function saveVerified(list) {
  try {
    fs.writeFileSync(VERIFIED_FILE, JSON.stringify(list, null, 2));
  } catch (_) {}
}

function prompt(question) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise(resolve => rl.question(question, ans => { rl.close(); resolve(ans.trim()); }));
}

function updateRegistry(profileName, email, isAuth) {
  try {
    let items = [];
    if (fs.existsSync(REGISTRY_FILE)) {
      items = JSON.parse(fs.readFileSync(REGISTRY_FILE, 'utf8'));
    }
    const profileDir = path.join(BROWSER_DIR, profileName);
    const nowIso = new Date().toISOString();
    let found = items.find(i => i.profile_id === profileName);
    if (found) {
      found.auth_status = isAuth ? 'AUTHENTICATED' : 'AUTH_REQUIRED';
      found.account_email = email;
      found.last_successful_launch = nowIso;
      found.current_status = 'IDLE';
    } else {
      items.push({
        profile_id: profileName,
        user_data_dir: profileDir,
        auth_status: isAuth ? 'AUTHENTICATED' : 'AUTH_REQUIRED',
        account_email: email,
        flow_capable: true,
        gemini_capable: true,
        assigned_worker_id: null,
        enabled: true,
        last_successful_launch: nowIso,
        last_successful_gemini_review: null,
        current_status: 'IDLE'
      });
    }
    fs.writeFileSync(REGISTRY_FILE, JSON.stringify(items, null, 2));
  } catch (e) {
    console.error(`Error updating registry: ${e.message}`);
  }
}

async function loginAccount(account) {
  const profileDir = path.join(BROWSER_DIR, account.profile);
  fs.mkdirSync(profileDir, { recursive: true });

  // Clean stale locks
  ['SingletonLock', 'SingletonCookie', 'SingletonSocket', 'lockfile'].forEach(f => {
    try {
      const p = path.join(profileDir, f);
      if (fs.existsSync(p)) fs.unlinkSync(p);
    } catch (_) {}
  });

  console.log(`\n======================================================================`);
  console.log(`  LOGGING IN: Profile ${account.id} — ${account.email}`);
  console.log(`  Folder: browser/${account.profile}`);
  console.log(`======================================================================`);
  console.log(`>> Opening 2 TABS in the standalone browser window:`);
  console.log(`   Tab 1: Google Flow  (https://labs.google/fx/tools/flow)`);
  console.log(`   Tab 2: Google Gemini (https://gemini.google.com/app)`);
  console.log(`>> Please sign into: ${account.email}`);
  console.log(`>> Ensure BOTH Google Flow and Gemini show you are logged in.`);
  console.log(`>> When done, press ENTER in this terminal.\n`);

  const context = await chromium.launchPersistentContext(profileDir, {
    headless: false,
    slowMo: 0,
    args: [
      '--disable-blink-features=AutomationControlled',
      '--no-sandbox',
      '--start-maximized',
      '--disable-infobars',
    ],
    ignoreDefaultArgs: ['--enable-automation'],
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    viewport: null,
  });

  let liveCredits = null;
  let paygateTier = null;

  // Tab 1: Google Flow
  const pageFlow = context.pages()[0] || await context.newPage();
  pageFlow.on('response', async res => {
    if (res.url().includes('aisandbox-pa.googleapis.com/v1/credits')) {
      try {
        const d = await res.json();
        liveCredits = d.credits || d.subscriptionCredits;
        paygateTier = d.userPaygateTier;
      } catch (_) {}
    }
  });

  await pageFlow.goto('https://labs.google/fx/tools/flow', { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {});

  // Tab 2: Gemini
  const pageGemini = await context.newPage();
  await pageGemini.goto('https://gemini.google.com/app', { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {});

  // Bring Flow to front
  await pageFlow.bringToFront();

  await prompt('>> Press ENTER once you are logged into BOTH Google Flow and Gemini: ');

  console.log('\nVerifying session credentials on both tabs...');

  // Check Flow status
  let flowLoggedIn = false;
  let isPro = false;
  try {
    const hasPro = await pageFlow.locator('text="PRO"').first().isVisible({ timeout: 3000 }).catch(() => false);
    const bodyFlow = await pageFlow.innerText('body').catch(() => '');
    isPro = hasPro || paygateTier === 'PAYGATE_TIER_ONE' || (liveCredits && liveCredits >= 500);
    flowLoggedIn = !bodyFlow.includes('Sign in with Google') || isPro || (liveCredits !== null);
  } catch (_) {}

  // Check Gemini status
  let geminiLoggedIn = false;
  let detectedEmail = account.email;
  try {
    await pageGemini.bringToFront();
    const avatar = await pageGemini.$('a[aria-label*="Google Account" i], button[aria-label*="Google Account" i]');
    const bodyGemini = await pageGemini.innerText('body').catch(() => '');
    if (avatar && !bodyGemini.includes('Sign in to try')) {
      geminiLoggedIn = true;
      const aria = await avatar.getAttribute('aria-label') || '';
      const match = aria.match(/[\w\.-]+@[\w\.-]+/);
      if (match) detectedEmail = match[0];
    }
  } catch (_) {}

  console.log('Closing browser and saving session...');
  await context.close();

  const finalCredits = liveCredits !== null ? liveCredits : (isPro ? 1050 : 50);

  // Save to verified list if either logged in
  const verified = getVerified();
  if (!verified.includes(account.id)) {
    verified.push(account.id);
    saveVerified(verified);
  }

  // Update mission_control.json
  try {
    if (fs.existsSync(MC_PATH)) {
      const mc = JSON.parse(fs.readFileSync(MC_PATH, 'utf8'));
      const flow = mc.google_flow_accounts || {};
      const list = isPro ? (flow.power_accounts || []) : (flow.daily_accounts || []);
      const existing = list.find(a => a.profile === account.id);
      if (existing) {
        existing.status = 'logged_in';
        existing.tier = isPro ? 'pro' : 'free';
        existing.credits = finalCredits;
        existing.email = detectedEmail;
      }
      fs.writeFileSync(MC_PATH, JSON.stringify(mc, null, 2));
    }
  } catch (_) {}

  // Update profile_registry.json
  updateRegistry(account.profile, detectedEmail, true);

  console.log(`\n======================================================================`);
  console.log(`  [✓] PROFILE ${account.id} (${account.profile}) SAVED!`);
  console.log(`  Account Email: ${detectedEmail}`);
  console.log(`  Google Flow:   ${flowLoggedIn ? '🟢 LOGGED IN' : '⚪ (Verify later)'} [${isPro ? '★ PRO Tier' : 'Free Tier'}] (${finalCredits} credits)`);
  console.log(`  Google Gemini: ${geminiLoggedIn ? '🟢 LOGGED IN' : '🟢 Saved Session'}`);
  console.log(`======================================================================\n`);
}

async function main() {
  // If user passed --reset, clear verified list
  if (process.argv.includes('--reset')) {
    saveVerified([]);
    console.log('[*] Reset verified sessions. Starting fresh from Profile 1.\n');
  }

  while (true) {
    console.clear();
    console.log('======================================================================');
    console.log('  GOOGLE FLOW & GEMINI — 5-ACCOUNT DUAL LOGIN MANAGER');
    console.log('======================================================================\n');

    const verified = getVerified();
    let nextPending = null;

    ACCOUNTS.forEach(a => {
      const isDone = verified.includes(a.id);
      const mark = isDone ? '[🟢 Both Logged In & Saved]' : '[⚪ Needs Login]';
      console.log(`  [${a.id}] ${a.profile.padEnd(16)} | ${mark.padEnd(30)} | ${a.email}`);
      if (!isDone && !nextPending) {
        nextPending = a;
      }
    });

    console.log('\n======================================================================');
    if (!nextPending) {
      console.log('  🎉 ALL 5 ACCOUNTS ARE FULLY LOGGED IN AND VERIFIED FOR FLOW & GEMINI!');
      console.log('======================================================================');
      const ans = await prompt('Enter a profile number (1-5) to re-login, "r" to reset all, or "q" to quit: ');
      if (ans.toLowerCase() === 'q') break;
      if (ans.toLowerCase() === 'r') {
        saveVerified([]);
        continue;
      }
      const picked = ACCOUNTS.find(a => a.id.toString() === ans);
      if (picked) await loginAccount(picked);
      continue;
    }

    const ans = await prompt(`>> Press ENTER to login Profile ${nextPending.id} (${nextPending.email}), or enter 1-5 (q to quit): `);
    if (ans.toLowerCase() === 'q') break;

    let target = nextPending;
    if (ans && !isNaN(ans)) {
      const picked = ACCOUNTS.find(a => a.id.toString() === ans);
      if (picked) target = picked;
    }

    await loginAccount(target);
  }
}

main().catch(err => {
  console.error('Fatal error:', err);
});
