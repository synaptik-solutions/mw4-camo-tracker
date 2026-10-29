const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');const {isSupportedUnlock}=require('../src/unlockPolicy');
const main=fs.readFileSync(require.resolve('../src/main.js'),'utf8');
const start=main.indexOf('function saveCompletionReview('),end=main.indexOf('function stopDetector()',start);
const data=new Map(),saved=[],messages=[];
const context={require,Date,store:{get:(k,fallback)=>data.has(k)?data.get(k):fallback,set:(k,v)=>data.set(k,v)},
 mainWindow:{webContents:{send:(...args)=>messages.push(args)}},overlayWindow:null,canonicalWeaponName:x=>String(x||'').toUpperCase(),key:x=>String(x||'').toUpperCase(),isSupportedUnlock,
 saveUnlock:event=>{saved.push(event);return true;}};
vm.createContext(context);vm.runInContext(main.slice(start,end),context);
context.saveCompletionReview({rawText:'CHALLENGE COMPLETED | Get 15 player kills',image:'data:image/jpeg;base64,AAA'});
assert.equal(saved.length,0);const first=data.get('completionReviews')[0];assert(first.id);
context.saveCompletionReview({rawText:'CHALLENGE COMPLETED | Get 15 player kills'});assert.equal(data.get('completionReviews').length,1);
assert.equal(context.resolveCompletionReview('missing','M4','Gold').ok,false);
assert.equal(context.resolveCompletionReview(first.id,'M4','Made up camo').ok,false);assert.equal(saved.length,0);
assert(context.resolveCompletionReview(first.id,'M4','Gold').ok);assert.equal(saved.length,1);assert.equal(data.get('completionReviews').length,0);
context.saveCompletionReview({rawText:'CHALLENGE COMPLETED | Another requirement'});
const second=data.get('completionReviews')[0];assert(context.resolveCompletionReview(second.id,null,null).ok);assert.equal(saved.length,1);
for(let n=0;n<30;n++)context.saveCompletionReview({rawText:'CHALLENGE COMPLETED | Requirement '+n});
assert.equal(data.get('completionReviews').length,20);
console.log('PASS: review storage is bounded; capture/dismiss never write progress; assignment requires staged ID and supported catalog selection.');
