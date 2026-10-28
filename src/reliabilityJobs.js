class WorkerJobs {
  constructor(spawn,terminate,onProgress=()=>{}){this.spawn=spawn;this.terminate=terminate;this.onProgress=onProgress;this.active=new Map();}
  run(command,args,options={}){
    if(this.active.size)return Promise.reject(new Error('Another analysis is already running.'));
    return new Promise((resolve,reject)=>{
      const child=this.spawn(command,args,{...options,windowsHide:true});const job={child,reject,done:false};this.active.set(child,job);
      let buffer='',result=null,error='';
      const finish=(err,value)=>{if(job.done)return;job.done=true;this.active.delete(child);err?reject(err):resolve(value);};
      child.stdout.on('data',data=>{buffer+=data.toString();if(buffer.length>16*1024*1024){this.terminate(child);finish(new Error('Worker response exceeded its size limit.'));return;}
        let i;while((i=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,i).trim();buffer=buffer.slice(i+1);if(!line)continue;try{const p=JSON.parse(line);if(p.type==='job-result')result=p;else if(p.type==='job-progress')this.onProgress(p);else if(p.type==='error')error=p.message||'Analysis failed';}catch(_){}}
      });
      child.stderr.on('data',data=>{error=(error+data.toString()).slice(-4000);});child.on('error',err=>finish(err));child.on('close',code=>finish(code===0&&result?null:new Error(error||'Analysis stopped before producing a result.'),result));
    });
  }
  cancelAll(){for(const job of this.active.values()){job.done=true;this.terminate(job.child);job.reject(new Error('Analysis cancelled.'));}this.active.clear();}
}
module.exports={WorkerJobs};
