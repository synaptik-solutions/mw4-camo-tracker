const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('tracker', {
  getState: () => ipcRenderer.invoke('get-state'),
  saveSettings: (settings) => ipcRenderer.invoke('save-settings', settings),
  startDetector: () => ipcRenderer.invoke('start-detector'),
  stopDetector: () => ipcRenderer.invoke('stop-detector'),
  clearProgress: () => ipcRenderer.invoke('clear-progress'),
  testUnlock: (event) => ipcRenderer.invoke('test-unlock', event),
  onProgress: (callback) => ipcRenderer.on('progress-updated', (_, data) => callback(data)),
  onDetectorState: (callback) => ipcRenderer.on('detector-state', (_, data) => callback(data)),
  onDetectorEvent: (callback) => ipcRenderer.on('detector-event', (_, data) => callback(data)),
  onDetectorError: (callback) => ipcRenderer.on('detector-error', (_, data) => callback(data)),
  onDetectorMessage: (callback) => ipcRenderer.on('detector-message', (_, data) => callback(data)),
  onOverlayEvent: (callback) => ipcRenderer.on('overlay-event', (_, data) => callback(data))
});
