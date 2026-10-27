const { app, BrowserWindow, ipcMain, screen, desktopCapturer } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn, execFile } = require('child_process');
const Store = require('electron-store');
const { autoUpdater } = require('electron-updater');
const { weapons: camoWeapons } = require('./camoCatalog');

const DEFAULT_ZONES = [
  { name:'upper-right', x:0.58, y:0.05, width:0.40, height:0.40 },
  { name:'center', x:0.27, y:0.25, width:0.46, height:0.50 },
  { name:'weapon-reference', x:0.52, y:0.62, width:0.44, height:0.22 }
];
const store = new Store({ defaults: { settings: { monitorIndex:0, captureSourceType:'display', captureSourceName:'', scanFps:4, overlay:true, autoStart:true, captureZones:DEFAULT_ZONES }, progress:{ weapons:{}, events:[] } } });
let mainWindow, overlayWindow, watchBadgeWindow, zoneOverlayWindow, detectorProcess, lastOverlayTimer;
let quitting=false;
let updateState={status:'idle',version:app.getVersion(),percent:0,message:''};
autoUpdater.autoDownload=false;
autoUpdater.autoInstallOnAppQuit=true;

function key(v){return String(v||'').trim().toUpperCase();}
function sanitizeZones(raw){
  if(!Array.isArray(raw)) return DEFAULT_ZONES.map(z=>({...z}));
  const zones=[];
  for(let i=0;i<Math.min(raw.length,4);i++){
    const z=raw[i]||{};
    let x=Number(z.x),y=Number(z.y),width=Number(z.width),height=Number(z.height);
    if(![x,y,width,height].every(Number.isFinite)) continue;
    x=Math.min(Math.max(x,0),.95);y=Math.min(Math.max(y,0),.95);
    width=Math.min(Math.max(width,.03),1-x);height=Math.min(Math.max(height,.03),1-y);
    zones.push({name:String(z.name||`zone-${i+1}`).toLowerCase(),x,y,width,height});
  }
  if(zones.length && !zones.some(z=>z.name.includes('weapon')) && zones.length<4) zones.push({...DEFAULT_ZONES[2]});
  return zones.length?zones:DEFAULT_ZONES.map(z=>({...z}));
}
function getMonitors(){const p=screen.getPrimaryDisplay().id;return screen.getAllDisplays().map((d,index)=>({index,label:`Monitor ${index+1}`,bounds:d.bounds,size:d.size,scaleFactor:d.scaleFactor,primary:d.id===p}));}
function getSettings(){
  const s=store.get('settings')||{};
  const monitors=getMonitors();
  let monitorIndex=Number.isInteger(s.monitorIndex)?s.monitorIndex:0;
  if(monitorIndex<0||monitorIndex>=monitors.length) monitorIndex=0;
  const captureSourceType=s.captureSourceType==='window'?'window':'display';
  const captureSourceName=captureSourceType==='window'?String(s.captureSourceName||''):'';
  return {...s,monitorIndex,captureSourceType,captureSourceName,captureZones:sanitizeZones(s.captureZones)};
}
async function getCaptureSources(){
  const settings=getSettings();
  const sources=[{type:'display',name:'Selected display',label:'Display — selected monitor'}];
  try{
    const windows=await desktopCapturer.getSources({types:['window'],thumbnailSize:{width:0,height:0},fetchWindowIcons:false});
    const seen=new Set();
    for(const src of windows){
      const name=String(src.name||'').trim();
      if(!name||name==='MW4 Camo Tracker'||seen.has(name)) continue;
      seen.add(name);
      sources.push({type:'window',name,label:`Window — ${name}`});
    }
  }catch(_){ }
  if(settings.captureSourceType==='window'&&settings.captureSourceName&&!sources.some(x=>x.type==='window'&&x.name===settings.captureSourceName)){
    sources.push({type:'window',name:settings.captureSourceName,label:`Window — ${settings.captureSourceName} (not currently visible)`});
  }
  return sources;
}
function setUpdateState(p){updateState={...updateState,...p};mainWindow?.webContents.send('update-status',updateState);}
function configureUpdater(){
  if(!app.isPackaged){setUpdateState({status:'dev',message:'Updates are available in installed builds only.'});return;}
  autoUpdater.on('checking-for-update',()=>setUpdateState({status:'checking',message:'Checking for updates…',percent:0}));
  autoUpdater.on('update-available',i=>setUpdateState({status:'available',version:i.version,message:`Version ${i.version} is available.`,percent:0}));
  autoUpdater.on('update-not-available',i=>setUpdateState({status:'current',version:i?.version||app.getVersion(),message:'You already have the latest version.',percent:0}));
  autoUpdater.on('download-progress',p=>setUpdateState({status:'downloading',percent:Math.round(p.percent||0),message:`Downloading update… ${Math.round(p.percent||0)}%`}));
  autoUpdater.on('update-downloaded',i=>setUpdateState({status:'ready',version:i.version,percent:100,message:`Version ${i.version} is ready to install.`}));
  autoUpdater.on('error',e=>setUpdateState({status:'error',message:e?.message||'Update check failed.'}));
}

const weaponAliases=new Map();
for(const item of camoWeapons) for(const alias of [item.name,...(item.aliases||[])]) weaponAliases.set(key(alias),key(item.name));
function canonicalWeaponName(v){const r=key(v||'UNKNOWN');return weaponAliases.get(r)||r;}

function destroyAuxWindows(){clearTimeout(lastOverlayTimer);lastOverlayTimer=null;for(const w of [overlayWindow,watchBadgeWindow,zoneOverlayWindow]) if(w&&!w.isDestroyed()) w.destroy();overlayWindow=watchBadgeWindow=zoneOverlayWindow=null;}
function createMainWindow(){
  mainWindow=new BrowserWindow({width:1200,height:780,minWidth:980,minHeight:650,backgroundColor:'#0b1018',title:'MW4 Camo Tracker',webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,nodeIntegration:false}});
  mainWindow.loadFile(path.join(__dirname,'index.html'));
  mainWindow.on('close',()=>{if(!quitting){quitting=true;stopDetector();destroyAuxWindows();app.quit();}});
  mainWindow.on('closed',()=>{mainWindow=null;});
}
function createOverlayWindow(){overlayWindow=new BrowserWindow({width:410,height:116,frame:false,transparent:true,alwaysOnTop:true,resizable:false,skipTaskbar:true,focusable:false,show:false,webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,nodeIntegration:false}});overlayWindow.setIgnoreMouseEvents(true);overlayWindow.loadFile(path.join(__dirname,'overlay.html'));}
function positionOverlay(d){if(d&&overlayWindow&&!overlayWindow.isDestroyed()) overlayWindow.setBounds({x:d.bounds.x+d.bounds.width-428,y:d.bounds.y+42,width:410,height:116});}
function showWatchBadge(d){
  if(!d)return;
  if(!watchBadgeWindow||watchBadgeWindow.isDestroyed()){
    watchBadgeWindow=new BrowserWindow({width:132,height:28,frame:false,transparent:true,alwaysOnTop:true,resizable:false,skipTaskbar:true,focusable:false,show:false,hasShadow:false,webPreferences:{contextIsolation:true,nodeIntegration:false}});
    watchBadgeWindow.setIgnoreMouseEvents(true);watchBadgeWindow.setAlwaysOnTop(true,'screen-saver');
    const h='<!doctype html><html><body style="margin:0;background:transparent;overflow:hidden;font-family:Segoe UI,Arial,sans-serif"><div style="height:26px;display:flex;align-items:center;justify-content:center;gap:6px;padding:0 9px;background:rgba(8,14,24,.72);border:1px solid rgba(81,220,169,.75);border-radius:0 0 8px 8px;color:#eefcf7;font-size:10px;font-weight:700"><span style="width:6px;height:6px;border-radius:50%;background:#51dca9"></span>MW4 WATCHING</div></body></html>';
    watchBadgeWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(h)}`);
  }
  watchBadgeWindow.setBounds({x:d.bounds.x+Math.round((d.bounds.width-132)/2),y:d.bounds.y,width:132,height:28});watchBadgeWindow.showInactive();
}
function hideWatchBadge(){if(watchBadgeWindow&&!watchBadgeWindow.isDestroyed())watchBadgeWindow.hide();}
function closeCaptureSetup(){if(zoneOverlayWindow&&!zoneOverlayWindow.isDestroyed())zoneOverlayWindow.hide();}
function captureSetupHtml(zones,sources,settings){
  const safeZones=JSON.stringify(zones).replace(/</g,'\\u003c');
  const safeSources=JSON.stringify(sources).replace(/</g,'\\u003c');
  const selectedIndex=Math.max(0,sources.findIndex(x=>x.type===settings.captureSourceType&&(x.type==='display'||x.name===settings.captureSourceName)));
  return `<!doctype html><html><head><meta charset="utf-8"><style>
  *{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:rgba(0,0,0,.04);font-family:Segoe UI,Arial,sans-serif;user-select:none}.toolbar{position:fixed;z-index:9999;top:14px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:10px;padding:9px 12px;background:rgba(8,12,18,.94);border:1px solid #ff3b3b;border-radius:8px;color:white;font-size:12px;max-width:96vw}.toolbar b{color:#ff6b6b}.toolbar button,.toolbar select{border:0;border-radius:6px;padding:7px 10px;font-weight:700}.toolbar select{max-width:330px;background:#17202d;color:#fff}.toolbar button{cursor:pointer}.zone{position:absolute;border:3px solid #ff2424;background:rgba(255,0,0,.025);min-width:60px;min-height:45px;resize:both;overflow:hidden}.zone .handle{height:28px;padding:6px 8px;background:rgba(70,0,0,.80);color:white;font-size:11px;font-weight:800;cursor:move}.zone:after{content:'RESIZE';position:absolute;right:4px;bottom:3px;color:#fff;background:#b00000;padding:2px 4px;font-size:9px;font-weight:800}.hint{opacity:.75;white-space:nowrap}
  </style></head><body><div class="toolbar"><b>CAPTURE SOURCE</b><select id="source"></select><span class="hint">Window is recommended. Boxes are relative to the bound game source.</span><button id="done">Save & close</button></div><script>const zones=${safeZones};const sources=${safeSources};const select=document.getElementById('source');sources.forEach((s,i)=>{const o=document.createElement('option');o.value=String(i);o.textContent=s.label;o.selected=i===${selectedIndex};select.appendChild(o)});select.onchange=async()=>{const s=sources[Number(select.value)];if(s)await window.tracker.saveCaptureSource(s)};const clamp=(v,a,b)=>Math.min(Math.max(v,a),b);const save=()=>window.tracker.saveCaptureZones(zones);zones.forEach((z,i)=>{const el=document.createElement('div');el.className='zone';el.style.left=(z.x*100)+'%';el.style.top=(z.y*100)+'%';el.style.width=(z.width*100)+'%';el.style.height=(z.height*100)+'%';const h=document.createElement('div');h.className='handle';h.textContent=(z.name||('zone '+(i+1))).toUpperCase()+' CAPTURE ZONE';el.appendChild(h);document.body.appendChild(el);let dragging=false,sx=0,sy=0,sl=0,st=0;h.addEventListener('pointerdown',e=>{dragging=true;sx=e.clientX;sy=e.clientY;sl=el.offsetLeft;st=el.offsetTop;h.setPointerCapture(e.pointerId)});h.addEventListener('pointermove',e=>{if(!dragging)return;const nl=clamp(sl+e.clientX-sx,0,innerWidth-el.offsetWidth),nt=clamp(st+e.clientY-sy,0,innerHeight-el.offsetHeight);el.style.left=nl+'px';el.style.top=nt+'px'});h.addEventListener('pointerup',()=>{dragging=false;z.x=el.offsetLeft/innerWidth;z.y=el.offsetTop/innerHeight;z.width=el.offsetWidth/innerWidth;z.height=el.offsetHeight/innerHeight;save()});new ResizeObserver(()=>{z.x=el.offsetLeft/innerWidth;z.y=el.offsetTop/innerHeight;z.width=clamp(el.offsetWidth/innerWidth,.03,1-z.x);z.height=clamp(el.offsetHeight/innerHeight,.03,1-z.y)}).observe(el)});document.getElementById('done').onclick=async()=>{await save();await window.tracker.closeCaptureSetup()};</script></body></html>`;
}
async function openCaptureSetup(){
  stopDetector();const s=getSettings(),m=getMonitors(),d=m[s.monitorIndex]||m[0];if(!d)return false;
  const sources=await getCaptureSources();
  if(!zoneOverlayWindow||zoneOverlayWindow.isDestroyed()) zoneOverlayWindow=new BrowserWindow({x:d.bounds.x,y:d.bounds.y,width:d.bounds.width,height:d.bounds.height,frame:false,transparent:true,alwaysOnTop:true,resizable:false,skipTaskbar:true,focusable:true,show:false,hasShadow:false,webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,nodeIntegration:false}});
  zoneOverlayWindow.setIgnoreMouseEvents(false);zoneOverlayWindow.setAlwaysOnTop(true,'screen-saver');zoneOverlayWindow.setBounds(d.bounds);zoneOverlayWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(captureSetupHtml(s.captureZones,sources,s))}`);zoneOverlayWindow.show();zoneOverlayWindow.focus();return true;
}

function normalizeEvent(e){return{type:e.type||'unlock',weapon:canonicalWeaponName(e.weapon),family:e.family?key(e.family):null,number:Number.isInteger(e.number)?e.number:null,camo:e.camo?key(e.camo):null,rawText:e.rawText||'',confidence:typeof e.confidence==='number'?e.confidence:null,timestamp:e.timestamp||new Date().toISOString()};}
function getWeaponProgress(p,w){const k=canonicalWeaponName(w),c=p.weapons[k]||{unlocks:[],lastSeen:null};c.unlocks=Array.isArray(c.unlocks)?c.unlocks.map(key):[];return{key:k,current:c};}
function broadcastProgress(p){store.set('progress',p);mainWindow?.webContents.send('progress-updated',p);}
function saveUnlock(raw){const e=normalizeEvent(raw),p=store.get('progress'),{key:k,current:w}=getWeaponProgress(p,e.weapon);if(e.family&&Number.isInteger(e.number)&&e.number>0){const f=e.family.includes('MILITARY')?'MILITARY CAMO':e.family;if(f==='MILITARY CAMO'){for(let n=1;n<=e.number;n++){const t=`MILITARY CAMO ${n}`;if(!w.unlocks.includes(t))w.unlocks.push(t);}}else{const t=`${f} ${e.number}`;if(!w.unlocks.includes(t))w.unlocks.push(t);}}else if(e.camo&&!w.unlocks.includes(e.camo))w.unlocks.push(e.camo);w.lastSeen=e.timestamp;p.weapons[k]=w;p.events.unshift({...e,weapon:k});p.events=p.events.slice(0,300);broadcastProgress(p);mainWindow?.webContents.send('detector-event',{...e,weapon:k});if(overlayWindow&&getSettings().overlay){const s=getSettings(),m=getMonitors(),d=m[s.monitorIndex]||m[0];positionOverlay(d);overlayWindow.webContents.send('overlay-event',{...e,weapon:k});overlayWindow.showInactive();clearTimeout(lastOverlayTimer);lastOverlayTimer=setTimeout(()=>{if(overlayWindow&&!overlayWindow.isDestroyed())overlayWindow.hide();},4500);}}
function setCamoStatus(weaponName,camoName,complete){const p=store.get('progress'),{key:k,current:c}=getWeaponProgress(p,weaponName),t=key(camoName);if(!t)return{ok:false};if(complete){const m=t.match(/^MILITARY CAMO (\d+)$/);if(m){const target=Math.max(1,Math.min(8,Number(m[1])));for(let n=1;n<=target;n++){const x=`MILITARY CAMO ${n}`;if(!c.unlocks.includes(x))c.unlocks.push(x);}}else if(!c.unlocks.includes(t))c.unlocks.push(t);}else{c.unlocks=c.unlocks.filter(x=>x!==t);const n=t.match(/^(MILITARY|SPECIAL|COMPLETIONIST|PRESTIGE) CAMO (\d+)$/);p.events=(p.events||[]).filter(e=>canonicalWeaponName(e.weapon)!==k||!(key(e.camo)===t||(n&&key(e.family)===`${n[1]} CAMO`&&Number(e.number)===Number(n[2]))));}c.lastSeen=c.lastSeen||new Date().toISOString();p.weapons[k]=c;broadcastProgress(p);return{ok:true};}
function stopDetector(){const p=detectorProcess;detectorProcess=null;if(p){try{if(process.platform==='win32'&&p.pid)execFile('taskkill',['/PID',String(p.pid),'/T','/F'],{windowsHide:true},()=>{});else p.kill('SIGTERM');}catch(_){try{p.kill();}catch(__){}}}hideWatchBadge();mainWindow?.webContents.send('detector-state',{running:false});}
function detectorCommand(){const e=app.isPackaged?path.join(process.resourcesPath,'worker','detector.exe'):path.join(__dirname,'..','worker-dist','detector.exe');if(fs.existsSync(e))return{command:e,prefixArgs:[]};const s=path.join(__dirname,'..','worker','detector_launcher.py');return process.platform==='win32'?{command:'py',prefixArgs:['-3',s]}:{command:'python3',prefixArgs:[s]};}
function startDetector(){
  closeCaptureSetup();stopDetector();const s=getSettings(),m=getMonitors(),d=m[s.monitorIndex]||m[0];if(!d){mainWindow?.webContents.send('detector-error','No display was found.');return false;}
  const windowMode=s.captureSourceType==='window'&&s.captureSourceName;
  const r=detectorCommand(),a=[...r.prefixArgs,'--monitor',String(windowMode?1:((d.index??s.monitorIndex??0)+1)),'--left',String(d.bounds.x),'--top',String(d.bounds.y),'--width',String(d.bounds.width),'--height',String(d.bounds.height),'--fps',String(s.scanFps||4),'--zones',JSON.stringify(s.captureZones)];
  const env={...process.env};if(windowMode)env.MW4_CAPTURE_WINDOW=s.captureSourceName;else delete env.MW4_CAPTURE_WINDOW;
  detectorProcess=spawn(r.command,a,{windowsHide:true,env});let b='';const sp=detectorProcess;
  sp.stdout.on('data',ch=>{b+=ch.toString();let n;while((n=b.indexOf('\n'))>=0){const l=b.slice(0,n).trim();b=b.slice(n+1);if(!l)continue;try{const x=JSON.parse(l);if(x.type==='unlock')saveUnlock(x);else if(x.type==='error')mainWindow?.webContents.send('detector-error',x.message||'Detector error');else mainWindow?.webContents.send('detector-message',x);}catch(_){}}});
  sp.stderr.on('data',ch=>mainWindow?.webContents.send('detector-log',ch.toString()));
  sp.on('error',e=>{if(detectorProcess!==sp)return;detectorProcess=null;hideWatchBadge();mainWindow?.webContents.send('detector-state',{running:false});mainWindow?.webContents.send('detector-error',`Could not start detector: ${e.message}`);});
  sp.on('exit',code=>{if(detectorProcess!==sp)return;detectorProcess=null;hideWatchBadge();mainWindow?.webContents.send('detector-state',{running:false,code});});
  showWatchBadge(d);mainWindow?.webContents.send('detector-state',{running:true,monitor:d.label,source:windowMode?s.captureSourceName:d.label});return true;
}

app.whenReady().then(()=>{
  createMainWindow();createOverlayWindow();configureUpdater();
  ipcMain.handle('get-state',()=>({settings:getSettings(),progress:store.get('progress'),monitors:getMonitors(),appVersion:app.getVersion(),update:updateState}));
  ipcMain.handle('save-settings',(_,s)=>{const current=getSettings();const monitors=getMonitors();const requested=Number.isInteger(s.monitorIndex)?s.monitorIndex:current.monitorIndex;const x={monitorIndex:requested>=0&&requested<monitors.length?requested:0,captureSourceType:s.captureSourceType==='window'?'window':current.captureSourceType,captureSourceName:s.captureSourceType==='window'?String(s.captureSourceName||''):current.captureSourceName,scanFps:[2,4,6].includes(Number(s.scanFps))?Number(s.scanFps):current.scanFps,overlay:Boolean(s.overlay),autoStart:Boolean(s.autoStart),captureZones:sanitizeZones(s.captureZones||current.captureZones)};store.set('settings',x);if(detectorProcess)startDetector();return{ok:true};});
  ipcMain.handle('save-capture-source',(_,source)=>{const s=getSettings();s.captureSourceType=source?.type==='window'?'window':'display';s.captureSourceName=s.captureSourceType==='window'?String(source?.name||''):'';store.set('settings',s);mainWindow?.webContents.send('capture-source-updated',{type:s.captureSourceType,name:s.captureSourceName});return{ok:true,source:{type:s.captureSourceType,name:s.captureSourceName}};});
  ipcMain.handle('open-capture-setup',async()=>({ok:await openCaptureSetup()}));
  ipcMain.handle('save-capture-zones',(_,zones)=>{const s=getSettings();s.captureZones=sanitizeZones(zones);store.set('settings',s);mainWindow?.webContents.send('capture-zones-updated',s.captureZones);return{ok:true,zones:s.captureZones};});
  ipcMain.handle('close-capture-setup',()=>{closeCaptureSetup();return{ok:true};});
  ipcMain.handle('reset-capture-zones',()=>{const s=getSettings();s.captureZones=DEFAULT_ZONES.map(z=>({...z}));store.set('settings',s);closeCaptureSetup();return{ok:true,zones:s.captureZones};});
  ipcMain.handle('start-detector',()=>({ok:startDetector()}));ipcMain.handle('stop-detector',()=>{stopDetector();return{ok:true};});ipcMain.handle('set-camo-status',(_,w,c,v)=>setCamoStatus(w,c,v));
  ipcMain.handle('clear-progress',()=>{const b={weapons:{},events:[]};broadcastProgress(b);return{ok:true};});ipcMain.handle('test-unlock',(_,e)=>{saveUnlock(e);return{ok:true};});
  ipcMain.handle('check-for-updates',async()=>{if(!app.isPackaged)return{ok:false,update:updateState};try{await autoUpdater.checkForUpdates();return{ok:true,update:updateState};}catch(e){setUpdateState({status:'error',message:e.message});return{ok:false,update:updateState};}});
  ipcMain.handle('download-update',async()=>{try{await autoUpdater.downloadUpdate();return{ok:true};}catch(e){setUpdateState({status:'error',message:e.message});return{ok:false};}});
  ipcMain.handle('install-update',()=>{if(updateState.status!=='ready')return{ok:false};quitting=true;stopDetector();destroyAuxWindows();setImmediate(()=>autoUpdater.quitAndInstall(false,true));return{ok:true};});
  if(getSettings().autoStart)setTimeout(startDetector,800);if(app.isPackaged)setTimeout(()=>autoUpdater.checkForUpdates().catch(()=>{}),2500);
});
app.on('before-quit',()=>{quitting=true;stopDetector();destroyAuxWindows();});
app.on('window-all-closed',()=>{if(process.platform!=='darwin')app.quit();});