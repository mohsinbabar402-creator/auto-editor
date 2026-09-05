/**
 * GOOGLE FLOW SMART LOGIN MANAGER
 * - Clean manual tracking so you only see what YOU actually logged into
 * - Defaults directly to Profile 4 (Blazing Soul)
 * - Just press ENTER to open and login
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
const readline = require('readline');

const PROJECT_DIR = 'C:\\Users\\ice\\Desktop\\youtube shorts project';
const BROWSER_DIR = path.join(PROJECT_DIR, 'browser');
const MC_PATH = path.join(PROJECT_DIR, 'mission_control.json');
const VERIFIED_FILE = path.join(PROJECT_DIR, 'verified_sessions.json');

const ACCOUNTS = [
  { id: 1, email: 'mohsinoctal777@gmail.com', name: 'Profile 1 (Verified)' },
  { id: 2, email: 'aoctal522@gmail.com', name: 'Profile 2 (Verified)' },
  { id: 3, email: 'mohsinmughal1771@gmail.com', name: 'Profile 3 (Verified)' },
  { id: 4, email: 'blazingsoul451@gmail.com', name: 'Profile 4 (Blazing Soul)' },
  { id: 5, email: 'zestify1771@gmail.com', name: 'Profile 5 (Zestify)' },
  { id: 6, email: 'donkeyraja646@gmail.com', name: 'Profile 6' },
  { id: 7, email: 'asa2333332@gmail.com', name: 'Profile 7' },
  { id: 8, email: 'zestify1122@gmail.com', name: 'Profile 8' },
  { id: 9, email: 'zestify7771@gmail.com', name: 'Profile 9' },
  { id: 10, email: 'zestify7744@gmail.com', name: 'Profile 10' },
  { id: 11, email: 'zestify1331@gmail.com', name: 'Profile 11' },
  { id: 12, email: 'zestifym1771@gmail.com', name: 'Profile 12' },
  { id: 13, email: 'zestifym1122@gmail.com', name: 'Profile 13' },
  { id: 14, email: 'zestifym77@gmail.com', name: 'Profile 14' },
  { id: 15, email: 'mohsinbabar402@gmail.com', name: 'Profile 15' },
];

function getVerified() {
  try {
    if (fs.existsSync(VERIFIED_FILE)) {
      return JSON.parse(fs.readFileSync(VERIFIED_FILE, 'utf8'));
    }
  } catch (_) {}
  // Default verified tonight
  return [1, 2, 3];
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

async function loginAccount(account) {
  const profileDir = path.join(BROWSER_DIR, `flow_profile_${account.id}`);
  fs.mkdirSync(profileDir, { recursive: true });

  // Clean stale locks
  ['SingletonLock', 'SingletonCookie', 'SingletonSocket', 'lockfile'].forEach(f => {
    try { const p = path.join(profileDir, f); if (fs.existsSync(p)) fs.unlinkSync(p); } catch (_) {}
  });

  console.log(`\n================================================`);
  console.log(`  OPENING CHROME FOR: Profile ${account.id} (${account.email})`);
  console.log(`================================================`);
  console.log(`>> The "T" logo Chrome window is opening on your screen.`);
  console.log(`>> Sign into: ${account.email}`);
  console.log(`>> When you see the Google Flow studio, press ENTER here.\n`);

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

  const page = context.pages()[0] || await context.newPage();
  await page.bringToFront();

  let liveCredits = null;
  let paygateTier = null;
  page.on('response', async res => {
    if (res.url().includes('aisandbox-pa.googleapis.com/v1/credits')) {
      try {
        const d = await res.json();
        liveCredits = d.credits || d.subscriptionCredits;
        paygateTier = d.userPaygateTier;
      } catch (_) {}
    }
  });

  await page.goto('https://labs.google/fx/tools/flow', { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {});
  const geminiPage = await context.newPage();
  await geminiPage.goto('https://gemini.google.com/app', { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {});
  await page.bringToFront();

  await prompt('>> Press ENTER once you are logged in: ');

  let hasPro = false;
  try {
    hasPro = await page.locator('text="PRO"').first().isVisible({ timeout: 2000 });
  } catch (_) {}

  console.log('\nSaving session...');
  await context.close();

  const isPro = hasPro || paygateTier === 'PAYGATE_TIER_ONE' || (liveCredits && liveCredits >= 500);
  const finalCredits = liveCredits !== null ? liveCredits : (isPro ? 1050 : 50);

  // Save to verified list
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
        existing.email = account.email;
      }
      fs.writeFileSync(MC_PATH, JSON.stringify(mc, null, 2));
    }
  } catch (_) {}

  // Update profile_registry.json for Gemini reviewer
  try {
    const regPath = path.join(BROWSER_DIR, 'profile_registry.json');
    let items = [];
    if (fs.existsSync(regPath)) {
      items = JSON.parse(fs.readFileSync(regPath, 'utf8'));
    }
    const profName = `flow_profile_${account.id}`;
    let found = items.find(i => i.profile_id === profName);
    if (found) {
      found.auth_status = 'AUTHENTICATED';
      found.account_email = account.email;
      found.current_status = 'IDLE';
    } else {
      items.push({
        profile_id: profName,
        user_data_dir: profileDir,
        auth_status: 'AUTHENTICATED',
        account_email: account.email,
        flow_capable: true,
        gemini_capable: true,
        assigned_worker_id: null,
        enabled: true,
        current_status: 'IDLE'
      });
    }
    fs.writeFileSync(regPath, JSON.stringify(items, null, 2));
  } catch (_) {}

  console.log(`\n[✓] Successfully saved Profile ${account.id}!`);
  console.log(`    Email:   ${account.email}`);
  console.log(`    Tier:    ${isPro ? '★ PRO (Google AI Pro)' : 'Free Tier'}`);
  console.log(`    Credits: ${finalCredits}\n`);
}

async function main() {
  while (true) {
    console.clear();
    console.log('================================================');
    console.log('  GOOGLE FLOW — 1-CLICK SEQUENTIAL LOGIN');
    console.log('================================================\n');

    const verified = getVerified();
    let nextPending = null;

    ACCOUNTS.forEach(a => {
      const isDone = verified.includes(a.id);
      const mark = isDone ? '[🟢 Logged In]' : '[⚪ Needs Login]';
      console.log(`  ${a.id.toString().padStart(2)}: ${a.email.padEnd(30)} ${mark}`);
      if (!isDone && !nextPending) {
        nextPending = a;
      }
    });

    console.log('\n================================================');
    if (!nextPending) {
      console.log('  🎉 ALL ACCOUNTS COMPLETED!');
      console.log('================================================\n');
      const ans = await prompt('Enter a profile number to re-login (or q to exit): ');
      if (ans.toLowerCase() === 'q') break;
      const target = ACCOUNTS.find(a => a.id === parseInt(ans));
      if (target) await loginAccount(target);
      continue;
    }

    console.log(`>> Next up: Profile ${nextPending.id} (${nextPending.email})`);
    console.log(`>> Just press ENTER to login this account (or type a number, or 'q'):`);
    const input = await prompt(`[default: Profile ${nextPending.id}]: `);

    if (input.toLowerCase() === 'q') break;

    let chosenAccount = nextPending;
    if (input && !isNaN(parseInt(input))) {
      const pickedId = parseInt(input);
      const picked = ACCOUNTS.find(a => a.id === pickedId);
      if (picked) {
        chosenAccount = picked;
      }
    }

    await loginAccount(chosenAccount);
    const cont = await prompt('Press ENTER for next account (or q to quit): ');
    if (cont.toLowerCase() === 'q') break;
  }
}

main().catch(err => console.error('Error:', err));
