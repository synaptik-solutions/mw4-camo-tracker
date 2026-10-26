const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('tracker', {
  getState: () => ipcRenderer.invoke('get-state'),
  saveSettings: (settings) => ipcRenderer.invoke('save-settings', settings),
  startDetector: () => ipcRenderer.invoke('start-detector'),
  stopDetector: () => ipcRenderer.invoke('stop-detector'),
  openCaptureSetup: () => ipcRenderer.invoke('open-capture-setup'),
  saveCaptureZones: (zones) => ipcRenderer.invoke('save-capture-zones', zones),
  closeCaptureSetup: () => ipcRenderer.invoke('close-capture-setup'),
  resetCaptureZones: () => ipcRenderer.invoke('reset-capture-zones'),
  clearProgress: () => ipcRenderer.invoke('clear-progress'),
  setCamoStatus: (weapon, camo, complete) => ipcRenderer.invoke('set-camo-status', weapon, camo, complete),
  testUnlock: (event) => ipcRenderer.invoke('test-unlock', event),
  checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),
  downloadUpdate: () => ipcRenderer.invoke('download-update'),
  installUpdate: () => ipcRenderer.invoke('install-update'),
  onProgress: (callback) => ipcRenderer.on('progress-updated', (_, data) => callback(data)),
  onDetectorState: (callback) => ipcRenderer.on('detector-state', (_, data) => callback(data)),
  onDetectorEvent: (callback) => ipcRenderer.on('detector-event', (_, data) => callback(data)),
  onDetectorError: (callback) => ipcRenderer.on('detector-error', (_, data) => callback(data)),
  onDetectorMessage: (callback) => ipcRenderer.on('detector-message', (_, data) => callback(data)),
  onUpdateStatus: (callback) => ipcRenderer.on('update-status', (_, data) => callback(data)),
  onOverlayEvent: (callback) => ipcRenderer.on('overlay-event', (_, data) => callback(data))
});
