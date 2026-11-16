(() => {
 const keys=["fluentpath-v2","fluentpath-state"]; let restoring=true,timer;
 async function syncDown(){try{const r=await fetch("/api/state");if(!r.ok)return;const p=await r.json();if(p.state&&Object.keys(p.state).length){for(const k of keys)if(p.state[k])localStorage.setItem(k,JSON.stringify(p.state[k]));if(!sessionStorage.getItem("fp_state_restored")){sessionStorage.setItem("fp_state_restored","1");location.reload();return;}}else{restoring=false;syncUp();return;}}catch(e){console.warn("Progress sync unavailable",e)}restoring=false;}
 async function syncUp(){if(restoring)return;const state={};for(const k of keys){try{const v=localStorage.getItem(k);if(v)state[k]=JSON.parse(v)}catch(_){}}try{await fetch("/api/state",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({state})})}catch(e){console.warn("Progress sync failed",e)}}
 const original=localStorage.setItem.bind(localStorage);localStorage.setItem=function(k,v){original(k,v);if(keys.includes(k)&&!restoring){clearTimeout(timer);timer=setTimeout(syncUp,450)}};
 syncDown();window.addEventListener("beforeunload",syncUp);
})();