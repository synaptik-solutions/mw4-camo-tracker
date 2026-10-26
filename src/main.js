const { app, BrowserWindow, ipcMain, screen } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const Store = require('electron-store');

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
    weapon: String(event.weapon || 'UNKNOWN').trim().toUpperCase(),
    family: event.family ? String(event.family).trim().toUpperCase() : null,
    number: Number.isInteger(event.number) ? event.number : null,
    camo: event.camo ? String(event.camo).trim().toUpperCase() : null,
    rawText: event.rawText || '',
    confidence: typeof event.confidence === 'number' ? event.confidence : null,
    timestamp: event.timestamp || new Date().toISOString()
  };
}

function saveUnlock(rawEvent) {
  const event = normalizeEvent(rawEvent);
  const progress = store.get('progress');
  const weapon = progress.weapons[event.weapon] || { unlocks: [], lastSeen: null };

  // If Camo 5 is seen after Camo 3, automatically backfill Camo 4.
  if (event.family && Number.isInteger(event.number) && event.number > 0) {
    for (let n = 1; n <= event.number; n += 1) {
      const token = `${event.family} ${n}`;
      if (!weapon.unlocks.includes(token)) weapon.unlocks.push(token);
    }
  } else if (event.camo && !weapon.unlocks.includes(event.camo)) {
    weapon.unlocks.push(event.camo);
  }

  weapon.lastSeen = event.timestamp;
  progress.weapons[event.weapon] = weapon;
  progress.events.unshift(event);
  progress.events = progress.events.slice(0, 300);
  store.set('progress', progress);

  mainWindow?.webContents.send('progress-updated', progress);
  mainWindow?.webContents.send('detector-event', event);

  if (overlayWindow && store.get('settings.overlay')) {
    overlayWindow.webContents.send('overlay-event', event);
    overlayWindow.showInactive();
    clearTimeout(lastOverlayTimer);
    lastOverlayTimer = setTimeout(() => {
      if (overlayWindow && !overlayWindow.isDestroyed()) overlayWindow.hide();
    }, 4500);
  }
}

function stopDetector() {
  if (detectorProcess) {
    try { detectorProcess.kill(); } catch (_) {}
    detectorProcess = null;
  }
  mainWindow?.webContents.send('detector-state', { running: false });
}

function detectorExecutablePath() {
  if (app.isPackaged) return path.join(process.resourcesPath, 'worker', 'detector.exe');
  return path.join(__dirname, '..', 'worker-dist', 'detector.exe');
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

  const exe = detectorExecutablePath();
  const args = [
    '--left', String(display.bounds.x),
    '--top', String(display.bounds.y),
    '--width', String(display.bounds.width),
    '--height', String(display.bounds.height),
    '--fps', String(settings.scanFps || 4)
  ];

  try {
    detectorProcess = spawn(exe, args, { windowsHide: true });
  } catch (error) {
    mainWindow?.webContents.send('detector-error', `Could not start detector: ${error.message}`);
    return false;
  }

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
        else mainWindow?.webContents.send('detector-message', message);
      } catch (_) {}
    }
  });

  detectorProcess.stderr.on('data', (chunk) => {
    mainWindow?.webContents.send('detector-log', chunk.toString());
  });

  detectorProcess.on('error', (error) => {
    mainWindow?.webContents.send('detector-error', error.message);
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

  ipcMain.handle('get-state', () => ({
    settings: store.get('settings'),
    progress: store.get('progress'),
    monitors: getMonitors()
  }));

  ipcMain.handle('save-settings', (_, settings) => {
    store.set('settings', settings);
    if (detectorProcess) startDetector();
    return { ok: true };
  });

  ipcMain.handle('start-detector', () => ({ ok: startDetector() }));
  ipcMain.handle('stop-detector', () => { stopDetector(); return { ok: true }; });
  ipcMain.handle('clear-progress', () => {
    const blank = { weapons: {}, events: [] };
    store.set('progress', blank);
    mainWindow?.webContents.send('progress-updated', blank);
    return { ok: true };
  });
  ipcMain.handle('test-unlock', (_, event) => { saveUnlock(event); return { ok: true }; });

  if (store.get('settings.autoStart')) setTimeout(startDetector, 800);
});

app.on('window-all-closed', () => {
  stopDetector();
  if (process.platform !== 'darwin') app.quit();
});
