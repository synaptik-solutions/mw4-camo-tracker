const React=require('react');
const {weapons,allCamosForWeapon}=require('./camoCatalog');

function ReviewCard({item,onResolve}){
  const [weapon,setWeapon]=React.useState('');
  const [camo,setCamo]=React.useState('');
  const [busy,setBusy]=React.useState(false);
  const [error,setError]=React.useState('');
  const [imageOpen,setImageOpen]=React.useState(false);
  const [actualSize,setActualSize]=React.useState(false);
  const imageClose=React.useRef(null);
  const imageOpener=React.useRef(null);
  React.useEffect(()=>{
    if(!imageOpen)return;
    imageClose.current?.focus();
    const escape=e=>{if(e.key==='Escape'){setImageOpen(false);imageOpener.current?.focus();}};
    window.addEventListener('keydown',escape);
    return()=>window.removeEventListener('keydown',escape);
  },[imageOpen]);
  const selected=weapons.find(w=>w.name===weapon);
  async function resolve(assign){
    setBusy(true);setError('');
    try{const result=await onResolve(item.id,assign?weapon:null,assign?camo:null);if(!result?.ok)setError(result?.error||'Unable to save.');}
    catch(e){setError(e.message);}finally{setBusy(false);}
  }
  return <section className="card" style={{marginBottom:16}}>
    <span className="eyebrow">BANNER NEEDS REVIEW</span>
    <p>{item.rawText}</p>
    {item.image&&<div>
      <img src={item.image} alt="Captured completion banner with surrounding screen" style={{display:'block',width:'100%',maxWidth:1200,height:'auto',objectFit:'contain'}}/>
      <button ref={imageOpener} className="ghost" onClick={()=>{setActualSize(false);setImageOpen(true);}}>View larger image</button>
    </div>}
    {imageOpen&&<div role="dialog" aria-modal="true" aria-label="Captured banner image" style={{position:'fixed',inset:0,zIndex:1000,background:'#080c12',display:'flex',flexDirection:'column',padding:20}}>
      <div className="buttons" style={{flexShrink:0,marginBottom:16}}>
        <button className="ghost" onClick={()=>setActualSize(value=>!value)}>{actualSize?'Fit image':'Actual size'}</button>
        <button ref={imageClose} className="primary" onClick={()=>{setImageOpen(false);imageOpener.current?.focus();}}>Close image</button>
      </div>
      <div style={{overflow:'auto',flex:1,minHeight:0}}>
        <img src={item.image} alt="Enlarged captured completion banner" style={actualSize?{display:'block',maxWidth:'none',height:'auto'}:{display:'block',width:'100%',height:'100%',objectFit:'contain'}}/>
      </div>
    </div>}
    <p className="muted">This banner was captured without a confirmed weapon and camo. Review it before assigning progress, or dismiss it if it is another challenge.</p>
    <div className="buttons">
      <select aria-label="Banner weapon" value={weapon} disabled={busy} onChange={e=>{setWeapon(e.target.value);setCamo('');}}><option value="">Choose weapon</option>{weapons.map(w=><option key={w.name}>{w.name}</option>)}</select>
      <select aria-label="Banner camo" value={camo} disabled={!selected||busy} onChange={e=>setCamo(e.target.value)}><option value="">Choose camo</option>{selected&&allCamosForWeapon(selected).map(c=><option key={c.name}>{c.name}</option>)}</select>
      <button className="primary" disabled={!weapon||!camo||busy} onClick={()=>resolve(true)}>Assign camo</button>
      <button className="ghost" disabled={busy} onClick={()=>resolve(false)}>Dismiss</button>
    </div>{error&&<p className="error">{error}</p>}
  </section>;
}
function CompletionReviews({items=[],onResolve}){
  return items.length>0&&<div><h3>Captured banners to review ({items.length})</h3>{items.map(item=><ReviewCard key={item.id} item={item} onResolve={onResolve}/>)}</div>;
}
module.exports={CompletionReviews};
