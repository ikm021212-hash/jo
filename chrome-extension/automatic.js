let automaticRun=null;
let automaticStop=false;
const autoSleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const shouldPause=error=>error.pause || /보안 확인|로그인 화면|접근 제한|사용자 중지|외부 페이지|인증 정보|No tab|permission|Cannot access/i.test(error.message);

async function localRequest(base,path,body,timeout=15000) {
  const response=await fetch(base+'/api'+path,{method:body===undefined?'GET':'POST',
    headers:{'X-Local-Client':'smallcloset','Content-Type':'application/json'},
    ...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(timeout)});
  const result=await response.json();
  if (!response.ok) throw new Error(typeof result.detail==='string'?result.detail:'수집 데이터 형식 확인 필요');
  return result;
}

async function automaticPage(tabId,mode,arg) {
  const current=await chrome.tabs.get(tabId);
  const url=new URL(current.url||'about:blank');
  if(url.protocol!=='https:' || !['sinsangmarket.kr','www.sinsangmarket.kr'].includes(url.hostname)){
    const error=new Error('신상마켓 외부 페이지로 이동해 자동 수집을 중지합니다. 로그인 후 상품 목록으로 돌아오세요.');error.pause=true;throw error;
  }
  await chrome.scripting.executeScript({target:{tabId},files:['capture.js','automatic-page.js']});
  const result=await chrome.scripting.executeScript({target:{tabId},func:(mode,arg)=>{
    if(mode==='listing')return inspectListingPage();
    if(mode==='inspect')return inspectAutomaticPage();
    if(mode==='detail')return openObservedDetail(arg);
    if(mode==='image')return readImagePixels(arg);
    if(mode==='scroll'){scrollBy(0,innerHeight*0.8);return true;}
  },args:[mode,arg??null]});
  const value=result[0]?.result;
  if(value?.capture_error){const error=new Error(value.capture_error);error.pause=true;throw error;}
  if(value===undefined)throw new Error('현재 페이지를 읽을 수 없습니다.');
  return value;
}

async function navigateAutomatically(tabId,url) {
  const target=new URL(url);
  if(target.protocol!=='https:' || !['sinsangmarket.kr','www.sinsangmarket.kr'].includes(target.hostname))throw new Error('허용되지 않은 외부 페이지로 자동 이동하지 않습니다.');
  await chrome.tabs.update(tabId,{url});await autoSleep(200);
  const until=Date.now()+30000;
  while(Date.now()<until){
    const tab=await chrome.tabs.get(tabId);
    if(tab.status==='complete' && !tab.pendingUrl){await autoSleep(800);return;}
    if(automaticStop)throw new Error('사용자 중지');
    await autoSleep(300);
  }
  throw new Error('페이지 로딩 시간 초과');
}

async function uploadObservedImage(config,tabId,source,ocr) {
  const pixels=await automaticPage(tabId,'image',source);
  if(pixels.error)throw new Error(pixels.error);
  let blob;
  if(pixels.data)blob=await(await fetch(pixels.data)).blob();
  else {
    const tab=await chrome.tabs.get(tabId);
    if(!tab.active)throw new Error('수집 탭이 비활성화되어 이미지 캡처를 하지 않음');
    const data=await chrome.tabs.captureVisibleTab(tab.windowId,{format:'png'});
    const image=await createImageBitmap(await(await fetch(data)).blob());
    const r=pixels.rect,sx=image.width/r.viewportWidth,sy=image.height/r.viewportHeight;
    const canvas=new OffscreenCanvas(Math.round(r.width*sx),Math.round(r.height*sy));
    canvas.getContext('2d').drawImage(image,r.x*sx,r.y*sy,r.width*sx,r.height*sy,0,0,canvas.width,canvas.height);
    blob=await canvas.convertToBlob({type:'image/png'});image.close();
  }
  const response=await fetch(config.base+'/api'+(ocr?'/ocr':'/images'),{method:'POST',
    headers:{'X-Local-Client':'smallcloset','Content-Type':'application/octet-stream'},body:blob,signal:AbortSignal.timeout(25000)});
  const result=await response.json();if(!response.ok)throw new Error(result.detail||'이미지 저장 실패');
  return {...result,url:'/api/evidence/'+result.evidence};
}

async function collectAutomaticItem(config,item,job) {
  const checkRunning=async()=>{
    const latest=await localRequest(config.base,`/companion/auto/${config.job_id}`);
    if(automaticStop || latest.state!=='running')throw new Error('사용자 중지');
  };
  const current=await chrome.tabs.get(config.tabId);
  if(current.url!==item.url)await navigateAutomatically(config.tabId,item.url);
  let observed=await automaticPage(config.tabId,'inspect');
  if(observed.name_source.startsWith('페이지 제목 후보') && item.listed_name){
    observed.name=item.listed_name;observed.name_source='실제 목록 상품 링크 title/alt';
  }
  const primary=observed;
  const evidence=[];const notes=[];
  if(observed.photo){
    try{observed.image_url=(await uploadObservedImage(config,config.tabId,observed.photo,false)).url;}
    catch(error){notes.push('대표 이미지: '+error.message);}
  }
  let charts=[...observed.charts];
  for(const label of ['제품설명','디테일컷']){
    await checkRunning();
    const view=await automaticPage(config.tabId,'detail',label);
    if(!view.opened)continue;
    if(view.href)await navigateAutomatically(config.tabId,view.href);else await autoSleep(700);
    const extra=await automaticPage(config.tabId,'inspect');
    observed.tables=[...observed.tables,...extra.tables].slice(0,20);
    observed.table_units=[...observed.table_units,...extra.table_units].slice(0,20);
    observed.selection=(observed.selection+'\n'+extra.selection).slice(0,1500);
    if(!observed.offers.length && extra.offers.length)observed.offers=extra.offers;
    charts=[...new Set([...extra.charts,...charts])];
    notes.push(label+' 화면 확인');
  }
  for(const source of charts.slice(0,2)){
    await checkRunning();
    try{
      const result=await uploadObservedImage(config,config.tabId,source,true);
      evidence.push(result.url);notes.push('이미지 사이즈표 OCR(미확정):\n'+result.text+'\n'+result.warning);
    }catch(error){
      // A security/login gate pauses the job rather than being bypassed.
      if(error.pause || /보안 확인|로그인 화면|접근 제한/.test(error.message))throw error;
      notes.push('이미지 사이즈표: '+error.message+' · 확인 필요');
    }
  }
  if(!observed.image_url && observed.photo){
    try{const url=new URL(observed.photo);if(url.protocol==='https:'){url.search='';url.hash='';observed.image_url=url.href;}}catch{}
  }
  delete observed.photo;delete observed.charts;
  return {...observed,url:primary.url,category:job.scope.category,confirmed_product:true,men_category_confirmed:true,
    image_url:observed.image_url||'',detail_note:notes.filter(note=>!note.startsWith('이미지 사이즈표 OCR')).join(' / ').slice(0,500),
    ocr_notes:notes.join('\n\n').slice(0,20000),evidence_images:evidence};
}

async function runAutomatic(config) {
  try{
    while(!automaticStop){
      const next=await localRequest(config.base,`/companion/auto/${config.job_id}/next`,{});
      if(next.filtered)continue;
      if(!next.item)break;
      const item=next.item;
      try{
        const page=await collectAutomaticItem(config,item,next.job);
        await localRequest(config.base,`/companion/auto/${config.job_id}/result`,{item_id:item.id,page});
      }catch(error){
        if(shouldPause(error))throw error;
        // At most one retry for a transient read/navigation error.
        await autoSleep(2500);
        if(automaticStop)break;
        try{
          const page=await collectAutomaticItem(config,item,next.job);
          await localRequest(config.base,`/companion/auto/${config.job_id}/result`,{item_id:item.id,page});
        }catch(second){
          if(shouldPause(second))throw second;
          await localRequest(config.base,`/companion/auto/${config.job_id}/result`,{item_id:item.id,error:second.message.slice(0,500)});
        }
      }
      // Sequential requests: no parallel product navigation.
      for(let i=0;i<20 && !automaticStop;i++)await autoSleep(100);
    }
    if(automaticStop)await localRequest(config.base,`/companion/auto/${config.job_id}/pause`,{reason:'사용자 일시정지'});
  }catch(error){
    await localRequest(config.base,`/companion/auto/${config.job_id}/pause`,{reason:error.message.slice(0,500)}).catch(()=>{});
  }finally{automaticRun=null;}
}

async function handleAutomaticMessage(message) {
  const port=Number(message.port);
  if(!Number.isInteger(port)||port<1||port>65535)throw new Error('프로그램 포트가 올바르지 않습니다.');
  const base=`http://127.0.0.1:${port}`;
  const saved=(await chrome.storage.local.get('automatic_config')).automatic_config;
  const jobId=Number(message.job_id || saved?.job_id);
  if(message.type==='auto-status')return jobId?{job:await localRequest(base,`/companion/auto/${jobId}`)}:{job:null};
  if(message.type==='auto-pause'){
    automaticStop=true;
    if(jobId)await localRequest(base,`/companion/auto/${jobId}/pause`,{reason:'사용자 일시정지'});
    return {job_id:jobId};
  }
  if(automaticRun)throw new Error('현재 수집을 중지한 뒤 다시 시작하세요.');
  const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
  if(!tab?.id)throw new Error('신상마켓 남성 상품 목록을 먼저 여세요.');
  await automaticPage(tab.id,'inspect'); // Never resume through a security gate.
  let job;
  if(message.type==='auto-start'){
    if(message.men_category_confirmed!==true)throw new Error('남성의류 목록임을 확인해 주세요.');
    const limit=Math.min(200,Math.max(1,Number(message.limit)||20));
    const found=new Map();let source='';let unchanged=0;const listPages=new Set();
    for(let round=0;round<6 && found.size<limit;round++){
      const page=await automaticPage(tab.id,'listing');source ||= page.source_url;
      const before=found.size;
      for(const item of page.candidates)if(!message.keyword || item.label.toLowerCase().includes(message.keyword.trim().toLowerCase()))found.set(item.url,item);
      unchanged=before===found.size?unchanged+1:0;
      if(found.size>=limit)break;
      if(unchanged>=2){
        if(page.next && listPages.size<2 && !listPages.has(page.next)){
          listPages.add(page.next);await navigateAutomatically(tab.id,page.next);unchanged=0;continue;
        }
        break;
      }
      await automaticPage(tab.id,'scroll');await autoSleep(900);
    }
    if(!found.size)throw new Error('현재 목록에서 이미지·표시 가격·실제 상품 링크를 함께 확인하지 못했습니다. 사이트 구조를 추측해 수집하지 않습니다.');
    const created=await localRequest(base,'/companion/auto/start',{source_url:source,candidates:[...found.values()].slice(0,200),limit,
      category:message.category||'미분류',keyword:message.keyword||'',men_category_confirmed:true});
    job=created.job;
  }else if(message.type==='auto-resume'){
    if(!jobId)throw new Error('재개할 작업 번호를 입력하세요.');
    job=await localRequest(base,`/companion/auto/${jobId}/resume`,{});
  }else throw new Error('지원하지 않는 자동 수집 명령입니다.');
  const config={base,job_id:job.id,tabId:tab.id};automaticStop=false;
  await chrome.storage.local.set({automatic_config:config,port,category:message.category||job.scope.category});
  automaticRun=runAutomatic(config);
  return {job_id:job.id,job};
}
