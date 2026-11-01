export function visibleDetections(items,end,windowHours=24){return items.filter(d=>{const time=Date.parse(d.observed_at);return Number.isFinite(time)&&time<=end&&time>=end-windowHours*3600000})}
export function playbackGate(time,frontier,complete,waiting){if(complete)return 'play';if(waiting)return frontier-time>=1.5?'play':'wait';return frontier-time<.12?'wait':'play'}
export function contiguousFrontier(frames,time,fps){let frontier=time;for(const frame of frames){if(frame.time<time-1/fps)continue;if(frame.time>frontier+1.5/fps)break;frontier=Math.max(frontier,frame.time+1/fps)}return frontier}

export function createMapEntrance(map,{reducedMotion=()=>false,visible=()=>true,schedule=setTimeout,unschedule=clearTimeout,now=()=>performance.now()}={}){
  let timer=null,lastStart=-Infinity,active=false;
  const cancel=()=>{
    if(timer!==null)unschedule(timer);
    timer=null;
    if(active){active=false;map.stop()}
  };
  const play=()=>{
    if(!visible()||active||now()-lastStart<3500)return;
    lastStart=now();
    if(reducedMotion()){map.jumpTo({zoom:1.3,pitch:0,bearing:0});return}
    const center=map.getCenter(),lat=Math.max(-65,Math.min(65,center.lat));
    active=true;
    const easing=t=>t*t*(3-2*t);
    map.easeTo({center:[center.lng+25,lat],zoom:1.95,pitch:8,bearing:0,duration:1300,easing});
    timer=schedule(()=>{
      timer=null;
      if(!visible()){cancel();return}
      map.easeTo({center:[center.lng+55,lat],zoom:1.3,pitch:0,bearing:0,duration:1900,easing});
      timer=schedule(()=>{timer=null;active=false},1900);
    },1300);
  };
  return {play,cancel,isActive:()=>active};
}

export function satelliteFeedStatus(minutes,refreshing,error){
  if(error)return error+' Automatic retries continue.';
  if(minutes>=15)return refreshing?'Updating satellite feed · cached observations shown.':'Satellite feed delayed · cached observations shown; retrying automatically.';
  if(minutes>=10)return refreshing?'Checking for new satellite data…':'Next satellite check due shortly.';
  return '';
}
