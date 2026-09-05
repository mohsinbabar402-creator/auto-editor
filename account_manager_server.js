const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const PORT = 3333;
const BASE_DIR = __dirname;
const BROWSER_DIR = path.join(BASE_DIR, 'browser');
const CONFIG_PATH = path.join(BASE_DIR, 'mission_control.json');
const CHROMIUM_EXE = "C:\\Users\\ice\\AppData\\Local\\ms-playwright\\chromium-1234\\chrome-win64\\chrome.exe";

if (!fs.existsSync(BROWSER_DIR)) fs.mkdirSync(BROWSER_DIR, { recursive: true });

function checkRealLoginState(profileNumber) {
  const profileDir = path.join(BROWSER_DIR, `flow_profile_${profileNumber}`);
  if (!fs.existsSync(profileDir)) return { is_logged_in: false, email: '' };

  const prefPath = path.join(profileDir, 'Default', 'Preferences');
  if (fs.existsSync(prefPath)) {
    try {
      const data = JSON.parse(fs.readFileSync(prefPath, 'utf-8'));
      const accs = data.account_info || [];
      if (Array.isArray(accs) && accs.length > 0 && accs[0].email) {
        return { is_logged_in: true, email: accs[0].email };
      }
    } catch (e) {}
  }
  return { is_logged_in: false, email: '' };
}

function loadAccounts() {
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      const data = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
      const power = (data.google_flow_accounts && data.google_flow_accounts.power_accounts) || [];
      const daily = (data.google_flow_accounts && data.google_flow_accounts.daily_accounts) || [];
      
      const all = [];
      power.forEach(p => all.push({ ...p, is_pro: true }));
      daily.forEach(d => all.push({ ...d, is_pro: false }));
      
      // Check REAL login status for each
      all.forEach(acc => {
        const state = checkRealLoginState(acc.profile);
        acc.is_logged_in = state.is_logged_in;
        acc.real_email = state.email || acc.email;
      });
      return all;
    }
  } catch (e) {
    console.error('Error loading config:', e);
  }
  return [];
}

function saveAccountToConfig(accData) {
  try {
    let data = {};
    if (fs.existsSync(CONFIG_PATH)) {
      data = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
    }
    if (!data.google_flow_accounts) data.google_flow_accounts = { power_accounts: [], daily_accounts: [] };
    
    data.google_flow_accounts.daily_accounts = (data.google_flow_accounts.daily_accounts || []).filter(a => a.profile !== accData.profile);
    data.google_flow_accounts.power_accounts = (data.google_flow_accounts.power_accounts || []).filter(a => a.profile !== accData.profile);
    
    const list = accData.is_pro ? data.google_flow_accounts.power_accounts : data.google_flow_accounts.daily_accounts;
    
    const entry = {
      priority: accData.priority || list.length + 1,
      profile: parseInt(accData.profile),
      label: accData.label || 'Account',
      email: accData.email || '',
      credits: accData.is_pro ? (accData.credits || 1050) : undefined,
      credits_daily: !accData.is_pro ? (accData.credits || 50) : undefined,
      tier: accData.is_pro ? 'banked' : 'free',
      status: 'ready'
    };
    
    list.push(entry);
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(data, null, 2), 'utf-8');
    return entry;
  } catch (e) {
    console.error('Save config error:', e);
  }
}

const activeSessions = {};

function launchLoginBrowser(profileId, label, email, isPro, res) {
  const profileDir = path.join(BROWSER_DIR, `flow_profile_${profileId}`);
  if (!fs.existsSync(profileDir)) fs.mkdirSync(profileDir, { recursive: true });

  activeSessions[profileId] = true;
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ success: true, message: `Opened browser window for Profile ${profileId}` }));

  console.log(`[UI Server] Spawning interactive browser window for Profile ${profileId} (${label})...`);

  const runBat = path.join(BASE_DIR, 'run_chrome.bat');
  const taskCmd = `schtasks /create /tn "LaunchFlowChrome" /tr "\"${runBat}\" \"${profileDir}\"" /sc once /st 23:59 /f /it && schtasks /run /tn "LaunchFlowChrome"`;

  const { exec } = require('child_process');
  exec(taskCmd, { shell: 'cmd.exe' }, (err) => {
    if (err) {
      console.error('schtasks launch error, falling back to direct start:', err);
      const fallbackCmd = `start "" "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --user-data-dir="${profileDir}" --no-first-run https://labs.google/fx/tools/flow`;
      exec(fallbackCmd, { shell: 'cmd.exe' });
    } else {
      console.log('[UI Server] Interactive window launched successfully via schtasks /it!');
    }
  });

  saveAccountToConfig({
    profile: profileId,
    label: label,
    email: email,
    is_pro: isPro,
    credits: isPro ? 1050 : 50
  });

  setTimeout(() => {
    delete activeSessions[profileId];
  }, 4000);
}

const server = http.createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, DELETE');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    return res.end();
  }

  const parsedUrl = new URL(req.url, `http://localhost:${PORT}`);
  const pathname = parsedUrl.pathname;

  if (pathname === '/' || pathname === '/index.html') {
    const htmlPath = path.join(BASE_DIR, 'public', 'account_manager.html');
    if (fs.existsSync(htmlPath)) {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(fs.readFileSync(htmlPath));
    }
  }

  if (pathname === '/api/accounts' && req.method === 'GET') {
    const accounts = loadAccounts();
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ accounts, activeSessions }));
  }

  if (pathname === '/api/accounts/login' && req.method === 'POST') {
    let body = '';
    req.on('data', chunk => (body += chunk));
    req.on('end', () => {
      try {
        const data = JSON.parse(body);
        const { profileId, label, email, isPro } = data;
        launchLoginBrowser(profileId, label, email, isPro, res);
      } catch (e) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }

  if (pathname.startsWith('/api/accounts/') && req.method === 'DELETE') {
    const pNum = parseInt(pathname.split('/').pop());
    try {
      if (fs.existsSync(CONFIG_PATH)) {
        const data = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
        if (data.google_flow_accounts) {
          data.google_flow_accounts.power_accounts = (data.google_flow_accounts.power_accounts || []).filter(a => a.profile !== pNum);
          data.google_flow_accounts.daily_accounts = (data.google_flow_accounts.daily_accounts || []).filter(a => a.profile !== pNum);
          fs.writeFileSync(CONFIG_PATH, JSON.stringify(data, null, 2), 'utf-8');
        }
      }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ success: true }));
    } catch (e) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: e.message }));
    }
  }

  res.writeHead(404);
  res.end('Not Found');
});

server.listen(PORT, () => {
  console.log(`Google Flow Account Hub running at http://localhost:${PORT}`);
});
