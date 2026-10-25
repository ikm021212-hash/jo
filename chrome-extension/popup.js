'use strict';
const $=selector=>document.querySelector(selector);
let ready=false;
function enableButtons(){for(const id of ['#capture','#auto-start'])$(id).disabled=!ready||!$('#confirmed').checked;}
chrome.storage.local.get({port:8000,category:'미분류',automatic_config:null}).then(saved=>{
  $('#port').value=saved.port;$('#category').value=saved.category;
  if(saved.automatic_config)$('#job-id').value=saved.automatic_config.job_id;
}).finally(()=>{ready=true;document.body.dataset.ready='true';enableButtons();refreshAutomatic();});
$('#confirmed').addEventListener('change',enableButtons);
async function send(type){
  const result=await chrome.runtime.sendMessage({type,port:Number($('#port').value),category:$('#category').value,
    limit:Number($('#limit').value),keyword:$('#keyword').value,job_id:Number($('#job-id').value)||null,
    confirmed_product:$('#confirmed').checked,men_category_confirmed:$('#confirmed').checked});
  if(!result?.ok)throw new Error(result?.error||'확장프로그램 처리 실패');
  return result;
}
async function refreshAutomatic(){
  if(!ready || !$('#job-id').value)return;
  try{
    const result=await send('auto-status');const job=result.job;if(!job)return;
    const states={running:'자동 수집 중',paused:'일시정지',completed:'완료'};
    $('#auto-status').textContent=`${states[job.state]||job.state} · ${job.done}/${job.total}개 저장 · 실패 ${job.failed}개\n${job.reason||''}`;
  }catch(error){$('#auto-status').textContent=error.message;}
}
$('#auto-start').addEventListener('click',async()=>{
  $('#auto-start').disabled=true;$('#auto-status').textContent='실제 목록 링크를 확인하는 중…';
  try{const result=await send('auto-start');$('#job-id').value=result.job_id;await refreshAutomatic();}
  catch(error){$('#auto-status').textContent=error.message;}
  finally{enableButtons();}
});
for(const [id,type] of [['#auto-pause','auto-pause'],['#auto-resume','auto-resume']])$(id).addEventListener('click',async()=>{
  try{const result=await send(type);if(result.job_id)$('#job-id').value=result.job_id;await refreshAutomatic();}
  catch(error){$('#auto-status').textContent=error.message;}
});
$('#capture').addEventListener('click',async()=>{
  $('#capture').disabled=true;$('#status').textContent='현재 상품 근거를 가져오는 중…';
  try{await send('capture-current-product');$('#status').textContent='검토용 초안을 저장했습니다.\n작은옷장 화면에서 근거를 확인하세요.';}
  catch(error){$('#status').textContent=error.message;}
  finally{enableButtons();}
});
setInterval(refreshAutomatic,1500);
