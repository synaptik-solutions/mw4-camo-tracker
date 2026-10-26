const { app, BrowserWindow, ipcMain, screen } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const Store = require('electron-store');
const { autoUpdater } = require('electron-updater');
const { weapons: camoWeapons } = require('./camoCatalog');

const store = new Store({
  defaults: {
    settings: { monitorIndex: 1, scanFps: 4, overlay: true, autoStart: true },
    progress: { weapons: {}, events: [] }
  }
});

let mainWindow;
let overlayWindow;
let detectorProcess;
let lastOverlayTimer;
let updateState = { status: 'idle', version: app.getVersion(), percent: 0, message: '' };

autoUpdater.autoDownload = false;
autoUpdater.autoInstallOnAppQuit = true;

function setUpdateState(patch) {
  updateState = { ...updateState, ...patch };
  mainWindow?.webContents.send('update-status', updateState);
}

function configureUpdater() {
  if (!app.isPackaged) {
    setUpdateState({ status: 'dev', message: 'Updates are available in installed builds only.' });
    return;
  }

  autoUpdater.on('checking-for-update', () => setUpdateState({ status: 'checking', message: 'Checking for updates…', percent: 0 }));
  autoUpdater.on('update-available', (info) => setUpdateState({ status: 'available', version: info.version, message: `Version ${info.version} is available.`, percent: 0 }));
  autoUpdater.on('update-not-available', (info) => setUpdateState({ status: 'current', version: info?.version || app.getVersion(), message: 'You already have the latest version.', percent: 0 }));
  autoUpdater.on('download-progress', (progress) => setUpdateState({ status: 'downloading', percent: Math.round(progress.percent || 0), message: `Downloading update… ${Math.round(progress.percent || 0)}%` }));
  autoUpdater.on('update-downloaded', (info) => setUpdateState({ status: 'ready', version: info.version, percent: 100, message: `Version ${info.version} is ready to install.` }));
  autoUpdater.on('error', (error) => setUpdateState({ status: 'error', message: error?.message || 'Update check failed.' }));
}

const weaponAliases = new Map();
for (const item of camoWeapons) {
  for (const alias of [item.name, ...(item.aliases || [])]) {
    weaponAliases.set(String(alias).trim().toUpperCase(), item.name.toUpperCase());
  }
}

function canonicalWeaponName(value) {
  const raw = String(value || 'UNKNOWN').trim().toUpperCase();
  return weaponAliases.get(raw) || raw;
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 780,
    minWidth: 980,
    minHeight: 650,
    backgroundColor: '#0b1018',
    title: 'MW4 Camo Tracker',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  mainWindow.loadFile(path.join(__dirname, 'index.html'));
}

function createOverlayWindow() {
  overlayWindow = new BrowserWindow({
    width: 410,
    height: 116,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    focusable: false,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  overlayWindow.setIgnoreMouseEvents(true);
  overlayWindow.loadFile(path.join(__dirname, 'overlay.html'));
}

function getMonitors() {
  const primaryId = screen.getPrimaryDisplay().id;
  return screen.getAllDisplays().map((display, index) => ({
    index,
    label: `Monitor ${index + 1}`,
    bounds: display.bounds,
    size: display.size,
    scaleFactor: display.scaleFactor,
    primary: display.id === primaryId
  }));
}

function normalizeEvent(event) {
  return {
    type: event.type || 'unlock',
    weapon: canonicalWeaponName(event.weapon),
    family: event.family ? String(event.family).trim().toUpperCase() : null,
    number: Number.isInteger(event.number) ? event.number : null,
    camo: event.camo ? String(event.camo).trim().toUpperCase() : null,
    rawText: event.rawText || '',
    confidence: typeof event.confidence === 'number' ? event.confidence : null,
    timestamp: event.timestamp || new Date().toISOString()
  };
}

function getWeaponProgress(progress, weaponName) {
  const key = canonicalWeaponName(weaponName);
  const current = progress.weapons[key] || { unlocks: [], lastSeen: null };
  current.unlocks = Array.isArray(current.unlocks) ? current.unlocks.map(x => String(x).toUpperCase()) : [];
  return { key, current };
}

function broadcastProgress(progress) {
  store.set('progress', progress);
  mainWindow?.webContents.send('progress-updated', progress);
}

function saveUnlock(rawEvent) {
  const event = normalizeEvent(rawEvent);
  const progress = store.get('progress');
  const { key, current: weapon } = getWeaponProgress(progress, event.weapon);

  if (event.family && Number.isInteger(event.number) && event.number > 0) {
    const family = event.family.includes('MILITARY') ? 'MILITARY CAMO' : event.family;
    for (let n = 1; n <= event.number; n += 1) {
      const token = `${family} ${n}`;
      if (!weapon.unlocks.includes(token)) weapon.unlocks.push(token);
    }
  } else if (event.camo && !weapon.unlocks.includes(event.camo)) {
    weapon.unlocks.push(event.camo);
  }

  weapon.lastSeen = event.timestamp;
  progress.weapons[key] = weapon;
  progress.events.unshift({ ...event, weapon: key });
  progress.events = progress.events.slice(0, 300);
  broadcastProgress(progress);

  mainWindow?.webContents.send('detector-event', { ...event, weapon: key });

  if (overlayWindow && store.get('settings.overlay')) {
    overlayWindow.webContents.send('overlay-event', { ...event, weapon: key });
    overlayWindow.showInactive();
    clearTimeout(lastOverlayTimer);
    lastOverlayTimer = setTimeout(() => {
      if (overlayWindow && !overlayWindow.isDestroyed()) overlayWindow.hide();
    }, 4500);
  }
}

function setCamoStatus(weaponName, camoName, complete) {
  const progress = store.get('progress');
  const { key, current } = getWeaponProgress(progress, weaponName);
  const token = String(camoName || '').trim().toUpperCase();
  if (!token) return { ok: false };

  const has = current.unlocks.includes(token);
  if (complete && !has) current.unlocks.push(token);
  if (!complete && has) current.unlocks = current.unlocks.filter(x => x !== token);
  current.lastSeen = current.lastSeen || new Date().toISOString();
  progress.weapons[key] = current;
  broadcastProgress(progress);
  return { ok: true };
}

function stopDetector() {
  if (detectorProcess) {
    try { detectorProcess.kill(); } catch (_) {}
    detectorProcess = null;
  }
  mainWindow?.webContents.send('detector-state', { running: false });
}

function detectorCommand() {
  const packagedExe = app.isPackaged
    ? path.join(process.resourcesPath, 'worker', 'detector.exe')
    : path.join(__dirname, '..', 'worker-dist', 'detector.exe');

  if (fs.existsSync(packagedExe)) return { command: packagedExe, prefixArgs: [] };

  const script = path.join(__dirname, '..', 'worker', 'detector.py');
  if (process.platform === 'win32') return { command: 'py', prefixArgs: ['-3', script] };
  return { command: 'python3', prefixArgs: [script] };
}

function startDetector() {
  stopDetector();

  const settings = store.get('settings');
  const monitors = getMonitors();
  const display = monitors[settings.monitorIndex] || monitors[1] || monitors[0];
  if (!display) {
    mainWindow?.webContents.send('detector-error', 'No display was found.');
    return false;
  }

  const runner = detectorCommand();
  const args = [
    ...runner.prefixArgs,
    '--left', String(display.bounds.x),
    '--top', String(display.bounds.y),
    '--width', String(display.bounds.width),
    '--height', String(display.bounds.height),
    '--fps', String(settings.scanFps || 4)
  ];

  detectorProcess = spawn(runner.command, args, { windowsHide: true });
  let stdoutBuffer = '';

  detectorProcess.stdout.on('data', (chunk) => {
    stdoutBuffer += chunk.toString();
    let newline;
    while ((newline = stdoutBuffer.indexOf('\n')) >= 0) {
      const line = stdoutBuffer.slice(0, newline).trim();
      stdoutBuffer = stdoutBuffer.slice(newline + 1);
      if (!line) continue;
      try {
        const message = JSON.parse(line);
        if (message.type === 'unlock') saveUnlock(message);
        else if (message.type === 'error') mainWindow?.webContents.send('detector-error', message.message || 'Detector error');
        else mainWindow?.webContents.send('detector-message', message);
      } catch (_) {}
    }
  });

  detectorProcess.stderr.on('data', (chunk) => {
    mainWindow?.webContents.send('detector-log', chunk.toString());
  });

  detectorProcess.on('error', (error) => {
    detectorProcess = null;
    mainWindow?.webContents.send('detector-state', { running: false });
    mainWindow?.webContents.send('detector-error', `Could not start detector: ${error.message}`);
  });

  detectorProcess.on('exit', (code) => {
    detectorProcess = null;
    mainWindow?.webContents.send('detector-state', { running: false, code });
  });

  mainWindow?.webContents.send('detector-state', { running: true, monitor: display.label });
  return true;
}

app.whenReady().then(() => {
  createMainWindow();
  createOverlayWindow();
  configureUpdater();

  ipcMain.handle('get-state', () => ({
    settings: store.get('settings'),
    progress: store.get('progress'),
    monitors: getMonitors(),
    appVersion: app.getVersion(),
    update: updateState
  }));

  ipcMain.handle('save-settings', (_, settings) => {
    const safeSettings = {
      monitorIndex: Number.isInteger(settings.monitorIndex) ? settings.monitorIndex : 1,
      scanFps: [2, 4, 6].includes(Number(settings.scanFps)) ? Number(settings.scanFps) : 4,
      overlay: Boolean(settings.overlay),
      autoStart: Boolean(settings.autoStart)
    };
    store.set('settings', safeSettings);
    if (detectorProcess) startDetector();
    return { ok: true };
  });

  ipcMain.handle('start-detector', () => ({ ok: startDetector() }));
  ipcMain.handle('stop-detector', () => { stopDetector(); return { ok: true }; });
  ipcMain.handle('set-camo-status', (_, weaponName, camoName, complete) => setCamoStatus(weaponName, camoName, complete));
  ipcMain.handle('clear-progress', () => {
    const blank = { weapons: {}, events: [] };
    broadcastProgress(blank);
    return { ok: true };
  });
  ipcMain.handle('test-unlock', (_, event) => { saveUnlock(event); return { ok: true }; });
  ipcMain.handle('check-for-updates', async () => {
    if (!app.isPackaged) return { ok: false, update: updateState };
    try { await autoUpdater.checkForUpdates(); return { ok: true, update: updateState }; }
    catch (error) { setUpdateState({ status: 'error', message: error.message }); return { ok: false, update: updateState }; }
  });
  ipcMain.handle('download-update', async () => {
    try { await autoUpdater.downloadUpdate(); return { ok: true }; }
    catch (error) { setUpdateState({ status: 'error', message: error.message }); return { ok: false }; }
  });
  ipcMain.handle('install-update', () => {
    if (updateState.status !== 'ready') return { ok: false };
    stopDetector();
    setImmediate(() => autoUpdater.quitAndInstall(false, true));
    return { ok: true };
  });

  if (store.get('settings.autoStart')) setTimeout(startDetector, 800);
  if (app.isPackaged) setTimeout(() => autoUpdater.checkForUpdates().catch(() => {}), 2500);
});

app.on('window-all-closed', () => {
  stopDetector();
  if (process.platform !== 'darwin') app.quit();
});
