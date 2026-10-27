// Windows capture bootstrap.
//
// Electron Display.bounds / BrowserWindow bounds are DIP (logical) coordinates, while the
// DPI-aware Python capture worker, MSS, Win32 and Windows Graphics Capture use physical
// screen pixels. Keep Electron UI geometry untouched and convert only detector spawn args.

const electron = require('electron');
const childProcess = require('child_process');

const originalSpawn = childProcess.spawn;
const originalSetTimeout = global.setTimeout;

// main.js uses a 2200 ms watchdog only for the small --resolve-window-bounds helper.
// A PyInstaller one-file executable may spend a few seconds unpacking on first launch or
// while antivirus scans it. Give that resolver a realistic window without slowing any of
// the app's normal timers (overlay hide, auto-start, updater checks, etc.).
global.setTimeout = function patchedSetTimeout(callback, delay, ...args) {
  const effectiveDelay = Number(delay) === 2200 ? 6000 : delay;
  return originalSetTimeout(callback, effectiveDelay, ...args);
};

function argIndex(args, name) {
  return Array.isArray(args) ? args.indexOf(name) : -1;
}

function numberAfter(args, name) {
  const i = argIndex(args, name);
  if (i < 0 || i + 1 >= args.length) return null;
  const value = Number(args[i + 1]);
  return Number.isFinite(value) ? value : null;
}

function setAfter(args, name, value) {
  const i = argIndex(args, name);
  if (i >= 0 && i + 1 < args.length) args[i + 1] = String(Math.round(value));
}

function physicalizeDetectorBounds(args) {
  if (process.platform !== 'win32' || !Array.isArray(args)) return args;
  if (args.includes('--resolve-window-bounds')) return args;

  const left = numberAfter(args, '--left');
  const top = numberAfter(args, '--top');
  const width = numberAfter(args, '--width');
  const height = numberAfter(args, '--height');
  if ([left, top, width, height].some(v => v === null)) return args;

  try {
    const physical = electron.screen.dipToScreenRect(null, {
      x: Math.round(left),
      y: Math.round(top),
      width: Math.max(1, Math.round(width)),
      height: Math.max(1, Math.round(height)),
    });
    const converted = [...args];
    setAfter(converted, '--left', physical.x);
    setAfter(converted, '--top', physical.y);
    setAfter(converted, '--width', physical.width);
    setAfter(converted, '--height', physical.height);
    return converted;
  } catch (_) {
    // Spawn unchanged rather than preventing the detector from starting. Diagnostics will
    // expose the resulting capture bounds if an unexpected Electron conversion failure occurs.
    return args;
  }
}

childProcess.spawn = function patchedSpawn(command, args, options) {
  const looksLikeDetector = Array.isArray(args) && args.includes('--zones') && args.includes('--fps');
  return originalSpawn.call(this, command, looksLikeDetector ? physicalizeDetectorBounds(args) : args, options);
};

require('./main.js');
