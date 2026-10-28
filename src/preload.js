const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('tracker', {
  getState: () => ipcRenderer.invoke('get-state'),
  saveSettings: async (settings) => {
    // Capture source is owned by the dedicated OBS-style source picker. The main React
    // view can hold a stale copy of settings while that overlay is open, so never let an
    // unrelated FPS/overlay/monitor save overwrite a newly selected window source.
    const currentState = await ipcRenderer.invoke('get-state');
    const current = currentState?.settings || {};
    return ipcRenderer.invoke('save-settings', {
      ...settings,
      captureSourceType: current.captureSourceType,
      captureSourceName: current.captureSourceName,
    });
  },
  startDetector: () => ipcRenderer.invoke('start-detector'),
  stopDetector: () => ipcRenderer.invoke('stop-detector'),
  openCaptureSetup: () => ipcRenderer.invoke('open-capture-setup'),
  saveCaptureSource: async (source) => {
    const result = await ipcRenderer.invoke('save-capture-source', source);
    // Rebuild the setup surface against the new source so any boxes that were dragged
    // into pixel coordinates cannot retain geometry from the previous display/window.
    await ipcRenderer.invoke('open-capture-setup');
    return result;
  },
  saveCaptureZones: (zones) => ipcRenderer.invoke('save-capture-zones', zones),
  closeCaptureSetup: () => ipcRenderer.invoke('close-capture-setup'),
  resetCaptureZones: () => ipcRenderer.invoke('reset-capture-zones'),
  getReliabilityState: () => ipcRenderer.invoke('get-reliability-state'),
  replayRecording: (expected=[]) => ipcRenderer.invoke('replay-recording',expected),
  openReplayReport: () => ipcRenderer.invoke('open-replay-report'),
  scanCamoMenu: weapon => ipcRenderer.invoke('scan-camo-menu',weapon),
  applyMenuReconciliation: (id,indices) => ipcRenderer.invoke('apply-menu-reconciliation',id,indices),
  cancelAnalysis: () => ipcRenderer.invoke('cancel-analysis'),
  openDiagnostics: () => ipcRenderer.invoke('open-diagnostics'),
  onReliabilityProgress: callback => {const listener=(_,data)=>callback(data);ipcRenderer.on('reliability-progress',listener);return()=>ipcRenderer.removeListener('reliability-progress',listener);},
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
  onDetectorMessage: (callback) => ipcRenderer.on('detector-message', (_, data) => {
    // The React diagnostics header already renders status.monitorSource. Promote the real
    // runtime backend from capture-health into that channel after capture has actually begun.
    if (data?.type === 'capture-health' && data.captureBackend) {
      callback({ type:'status', monitorSource:data.captureBackend, captureBackend:data.captureBackend });
    }
    callback(data);
  }),
  onUpdateStatus: (callback) => ipcRenderer.on('update-status', (_, data) => callback(data)),
  onOverlayEvent: (callback) => ipcRenderer.on('overlay-event', (_, data) => callback(data))
});

