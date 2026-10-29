const React=require('react');const {createRoot}=require('react-dom/client');
const {CompletionReviews}=require('../../src/CompletionReviews');
window.resolutions=[];
createRoot(document.getElementById('preview')).render(<CompletionReviews items={[{id:'banner-1',rawText:'CHALLENGE COMPLETED | Get 15 player kills in a single match'}]} onResolve={async(...args)=>{window.resolutions.push(args);return{ok:true};}}/>);
