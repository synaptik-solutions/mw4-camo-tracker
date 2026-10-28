function captureWarnings(heartbeat,receivedAt,running,now=Date.now()){
  if(!running)return[];
  const issues=[...(heartbeat?.issues||[])];
  if(receivedAt&&now-receivedAt>6000)issues.push('Capture heartbeat is missing. Stop and restart watching if it does not return.');
  for(const [zone,stats] of Object.entries(heartbeat?.zones||{})){
    if(Number(stats.blankForSec)>=3)issues.push(`${zone}: capture has been blank for ${Math.round(stats.blankForSec)} seconds.`);
    else if(Number(stats.unchangedForSec)>=8)issues.push(`${zone}: image is unchanged; this may be a static menu or stale capture.`);
  }
  return [...new Set(issues)];
}
module.exports={captureWarnings};
