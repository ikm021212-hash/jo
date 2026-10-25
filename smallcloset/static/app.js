'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const won = v => v == null ? '미확인' : Number(v).toLocaleString('ko-KR') + '원';
const statuses = {pass:'조건 충족', review:'확인 필요', fail:'조건 미충족'};
const stocks = {available:'구매 가능 확인', sold_out:'품절', unknown:'재고 미확인'};
let state = {products:[],rules:{},jobs:[]}, selected = new Set(), currentStatus = '', currentPane = 'results', editing = null, screenshotUrl = null, timer, busyScreen = false;
let collectedLinks = [];

async function api(path, method='GET', body) {
  const options = {method, headers:{'X-Local-Client':'smallcloset'}};
  if (body !== undefined) { options.headers['Content-Type']='application/json'; options.body=JSON.stringify(body); }
  const response = await fetch('/api'+path, options);
  if (!response.ok) {
    const data = await response.json().catch(()=>({detail:'요청 처리 실패'}));
    throw new Error(typeof data.detail === 'string' ? data.detail : '입력 형식과 필수 항목을 확인해 주세요.');
  }
  return response.json();
}
function toast(text) { $('#toast').textContent=text; $('#toast').classList.remove('hidden'); clearTimeout(timer); timer=setTimeout(()=>$('#toast').classList.add('hidden'),6000); }
async function act(fn) { try { await fn(); } catch(error) { toast(error.message); } }
function pane(name) { currentPane=name; $$('.pane').forEach(e=>e.classList.toggle('hidden',e.id!==name)); $$('.nav').forEach(e=>e.classList.toggle('active',e.dataset.pane===name)); if(name==='collect' && state.browser_open) act(refreshScreen); }
$$('[data-pane]').forEach(e=>e.addEventListener('click',()=>pane(e.dataset.pane)));

async function refresh(quiet=false) {
  const data = await api('/state');
  state=data;
  const supplier=$('#filter-supplier').value;
  $('#filter-supplier').innerHTML='<option value="">모든 거래처</option>'+[...new Set(state.products.map(p=>p.supplier).filter(Boolean))].sort().map(s=>`<option>${esc(s)}</option>`).join('');
  $('#filter-supplier').value=supplier;
  if(!quiet || !$('#rules-fields').children.length) renderRules();
  $('#browser-status').textContent=data.browser;
  $('#browser-shell').classList.toggle('hidden',!data.browser_open);
  renderProducts(); renderJobs();
}
function filtered() {
  const category=$('#filter-category').value, supplier=$('#filter-supplier').value;
  let products=state.products.filter(p=>(!currentStatus || p.decision.status===currentStatus) && (!category || p.category===category) && (!supplier || p.supplier===supplier) && (!$('#filter-favorite').checked || p.favorite) && ($('#show-excluded').checked || !p.excluded));
  const min=(p,key)=>{const vals=p.decision.options.map((o,i)=>key==='price' ? o.price : p.options[i]?.length_verified ? o.length : null).filter(v=>v!==null); return vals.length ? Math.min(...vals) : Infinity;};
  if($('#sort').value==='price') products.sort((a,b)=>min(a,'price')-min(b,'price'));
  if($('#sort').value==='length') products.sort((a,b)=>min(a,'length')-min(b,'length'));
  return products;
}
function renderProducts() {
  const all=state.products.filter(p=>$('#show-excluded').checked||!p.excluded);
  $('#count-all').textContent=all.length;
  for(const status of Object.keys(statuses)) $('#count-'+status).textContent=all.filter(p=>p.decision.status===status).length;
  const products=filtered();
  $('#result-count').textContent=products.length+'개 상품';
  $('#selection-count').textContent=selected.size ? selected.size+'개 선택 · CSV로 내보낼 수 있어요' : '선택하지 않으면 현재 필터 결과를 내보냅니다';
  $('#empty').classList.toggle('hidden',products.length>0);
  $('#product-grid').innerHTML=products.map(p=>{
    const known=[...p.decision.options.map(o=>o.price).filter(v=>v!==null),...(p.listing_min_price!=null?[p.listing_min_price]:[])], min=known.length?Math.min(...known):null;
    return `<article class="card ${p.excluded?'excluded':''}" data-id="${p.id}"><div class="card-image">${p.image_url?`<img src="${esc(p.image_url)}" alt="${esc(p.name)}" referrerpolicy="no-referrer" loading="lazy">`:''}<div class="image-fallback ${p.image_url?'hidden':''}"><strong>옷</strong>이미지 미확인<br><a href="${esc(p.url)}" target="_blank" rel="noreferrer">상품 원문에서 확인 ↗</a></div><input type="checkbox" class="card-select" aria-label="상품 선택" ${selected.has(p.id)?'checked':''}><button class="favorite ${p.favorite?'on':''}" data-action="favorite" aria-label="즐겨찾기">${p.favorite?'★':'☆'}</button></div><div class="card-body"><span class="badge ${p.decision.status}">${statuses[p.decision.status]}</span> <span class="small muted">${esc(p.category)} · ${esc(p.gender)}</span><div class="supplier">${esc(p.supplier||'거래처 미확인')}${p.location?' · '+esc(p.location):''}</div><h3>${esc(p.name||'상품명 미확인')}</h3><div class="price">${won(min)} ${known.length?'<small>확인된 옵션 중 최저</small>':''}</div><div class="measurements">${p.options.length?p.options.map((o,i)=>`<div class="${p.decision.options[i]?.status==='pass'?'matched':''}">${esc(o.size||'사이즈 미확인')} ${esc(o.color)} · 총장 ${esc(o.length_raw||'미확인')}<br><span class="small">${won(o.price)} + 추가금 ${won(o.extra_price)} · ${stocks[o.stock]||stocks.unknown}</span></div>`).join(''):'총장·옵션 근거를 입력해 주세요.'}</div>${p.keyword_hints?.length&&p.decision.status==='review'?`<span class="badge review">${esc(p.keyword_hints.join(" · "))} 문구 후보</span>`:""}<p class="reason">${esc(p.decision.reason)}</p>${p.memo?`<div class="memo-preview">${esc(p.memo)}</div>`:''}<details class="evidence"><summary>가격·총장 근거와 옵션 판정</summary>${p.options.map((o,i)=>`<p><b>${esc(o.size)} ${esc(o.color)}</b><br>가격: ${esc(o.price_evidence||'미확인')}<br>총장: ${esc(o.length_evidence||'미확인')}<br>${esc(p.decision.options[i]?.reason||'')}</p>`).join('')}<p>${esc(p.capture_note||'')}</p>${p.ocr_notes?`<p>${esc(p.ocr_notes)}</p>`:''}${(p.evidence_images||[]).map(path=>`<p><a href="${esc(path)}" target="_blank" rel="noreferrer">자동 확인한 사이즈표 원본</a></p>`).join('')}${p.separate_charges?`<p>별도 표기: ${esc(p.separate_charges)}</p>`:''}</details><div class="card-foot"><button data-action="edit">근거 · 메모 편집</button><button data-action="exclude">${p.excluded?'제외 해제':'제외'}</button><a href="${esc(p.url)}" target="_blank" rel="noreferrer">상품 원문 ↗</a><time>수집 ${new Date(p.collected_at).toLocaleString('ko-KR')}</time></div></div></article>`;
  }).join('');
  $$('.card-image img').forEach(img=>img.addEventListener('error',()=>{img.classList.add('hidden');img.parentElement.querySelector('.image-fallback').classList.remove('hidden');}));
}
$$('[data-status]').forEach(e=>e.addEventListener('click',()=>{currentStatus=e.dataset.status;$$('[data-status]').forEach(b=>b.classList.toggle('active',b===e));renderProducts();}));
['#filter-category','#filter-supplier','#sort','#filter-favorite','#show-excluded'].forEach(s=>$(s).addEventListener('change',renderProducts));
$('#product-grid').addEventListener('change',event=>{if(event.target.matches('.card-select')) {const id=Number(event.target.closest('.card').dataset.id);event.target.checked?selected.add(id):selected.delete(id);renderProducts();}});
$('#product-grid').addEventListener('click',event=>act(async()=>{
  const action=event.target.dataset.action; if(!action)return;
  const p=state.products.find(p=>p.id===Number(event.target.closest('.card').dataset.id));
  if(action==='edit')return openEditor(p);
  await api('/products/'+p.id,'PATCH',action==='favorite'?{favorite:!p.favorite}:{excluded:!p.excluded}); await refresh(true);
}));
$('#export').addEventListener('click',()=>act(async()=>{
  const ids=selected.size?[...selected]:filtered().map(p=>p.id); if(!ids.length)return toast('내보낼 상품이 없습니다.');
  const response=await fetch('/api/export?ids='+ids.join(',')); if(!response.ok)throw new Error('CSV 생성 실패');
  const url=URL.createObjectURL(await response.blob()), a=document.createElement('a');a.href=url;a.download='작은옷장_선별_'+new Date().toISOString().slice(0,10)+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}));

function renderRules(){ $('#rules-fields').innerHTML=Object.entries(state.rules).map(([category,r])=>`<div class="rule-row" data-category="${esc(category)}"><h3>${esc(category)}</h3><label>상품 가격 상한 · 원<input data-rule="price" type="number" value="${r.price}" min="0" max="100000000" required></label><label>총장 상한 · cm<input data-rule="length" type="number" value="${r.length}" min="0.1" max="250" step="0.1" required></label></div>`).join(''); }
$('#rules-form').addEventListener('submit',event=>{event.preventDefault();act(async()=>{const rules={};$$('.rule-row').forEach(e=>rules[e.dataset.category]={price:Number(e.querySelector('[data-rule=price]').value),length:Number(e.querySelector('[data-rule=length]').value)});await api('/rules','PUT',{rules});await refresh();toast('기준을 저장하고 모든 상품을 다시 판정했습니다.');});});

function openEditor(product=null){
  editing=product;$('#product-form').reset();$('#options').innerHTML='';$('#p-url').readOnly=!!product;
  $('#editor-title').textContent=product?'상품 근거 · 메모 편집':'상품 근거 입력';
  const fields={url:'url',name:'name',supplier:'supplier',location:'location',category:'category',gender:'gender',image:'image_url',charges:'separate_charges',memo:'memo',excerpt:'source_excerpt'};
  for(const [field,key] of Object.entries(fields)) $('#p-'+field).value=product?.[key]??(['category','gender'].includes(field)?'미확인':'');
  if(!product)$('#p-category').value='미분류';
  $('#p-set').checked=!!product?.inseparable_set;
  (product?.options?.length?product.options:[{}]).forEach(addOption);
  $('#ocr-text').value='';$('#ocr-status').textContent='';$('#ocr-ref').textContent='';$('#ocr-link').classList.add('hidden');
  $('#editor').showModal();
}
function addOption(o={}){
  const el=document.createElement('div');el.className='option';
  el.innerHTML=`<div class="option-head"><strong>같은 구매 옵션의 정보</strong><button type="button" class="remove-option">삭제</button></div><div class="form-row"><label>사이즈<input data-field="size" value="${esc(o.size)}" maxlength="100" placeholder="예: S"></label><label>색상<input data-field="color" value="${esc(o.color)}" maxlength="100"></label><label>품절 여부<select data-field="stock"><option value="unknown">미확인</option><option value="available">구매 가능 확인</option><option value="sold_out">품절</option></select></label></div><div class="form-row"><label>표시 가격 · 원<input data-field="price" type="number" min="0" max="100000000" step="1" value="${esc(o.price)}"></label><label>옵션 추가금 · 원<input data-field="extra_price" type="number" min="0" max="100000000" step="1" value="${esc(o.extra_price)}" placeholder="없음 확인 시 0"></label><label>총장 원문 · cm<input data-field="length_raw" value="${esc(o.length_raw)}" maxlength="500" placeholder="67 또는 67~69 또는 앞 65 / 뒤 68"></label></div><div class="form-row"><label>가격·추가금 원문 근거<input data-field="price_evidence" value="${esc(o.price_evidence)}" maxlength="2000" placeholder="원문 표시와 확인 위치"></label><label>총장 원문·사이즈표 근거<input data-field="length_evidence" value="${esc(o.length_evidence)}" maxlength="2000" placeholder="제품설명 탭의 S 총장 67cm 등"></label></div><div class="form-row"><label class="check"><input type="checkbox" data-field="price_verified" ${o.price_verified?'checked':''}>동일 옵션의 표시 가격과 추가금을 확인함</label><label class="check"><input type="checkbox" data-field="length_verified" ${o.length_verified?'checked':''}>원본의 총장 열·사이즈 행·단위를 직접 확인함</label></div>`;
  el.querySelector('[data-field=stock]').value=o.stock||'unknown';el.querySelector('.remove-option').addEventListener('click',()=>el.remove());$('#options').append(el);
}
$('#new-product').addEventListener('click',()=>openEditor());$('#editor-close').addEventListener('click',()=>$('#editor').close());$('#add-option').addEventListener('click',()=>addOption());
$('#product-form').addEventListener('submit',event=>{event.preventDefault();act(async()=>{
  const options=$$('#options .option').map(el=>{const o={};el.querySelectorAll('[data-field]').forEach(input=>{o[input.dataset.field]=input.type==='checkbox'?input.checked:input.type==='number'?(input.value===''?null:Number(input.value)):input.value;});return o;});
  const p={url:$('#p-url').value,name:$('#p-name').value,supplier:$('#p-supplier').value,location:$('#p-location').value,category:$('#p-category').value,gender:$('#p-gender').value,image_url:$('#p-image').value,inseparable_set:$('#p-set').checked,separate_charges:$('#p-charges').value,options,source_excerpt:$('#p-excerpt').value,capture_note:editing?.capture_note||'',source_type:editing?.source_type||'manual',ocr_notes:editing?.ocr_notes||'',evidence_images:editing?.evidence_images||[],listing_min_price:editing?.listing_min_price??null,listing_price_evidence:editing?.listing_price_evidence||''};
  const result=await api(editing?'/products/'+editing.id:'/products',editing?'PUT':'POST',p);await api('/products/'+result.id,'PATCH',{memo:$('#p-memo').value});$('#editor').close();await refresh(true);toast('상품 근거를 저장했습니다.');
});});
$('#ocr-file').addEventListener('change',()=>act(async()=>{
  const file=$('#ocr-file').files[0];if(!file)return;if(file.size>10000000)throw new Error('10MB 이하의 이미지를 선택하세요.');
  $('#ocr-status').textContent='로컬 OCR 처리 중…';const response=await fetch('/api/ocr',{method:'POST',headers:{'X-Local-Client':'smallcloset','Content-Type':'application/octet-stream'},body:file});
  const data=await response.json();if(!response.ok)throw new Error(data.detail||'OCR 오류');
  $('#ocr-text').value=data.text;$('#ocr-status').textContent=data.warning;const ref='/api/evidence/'+data.evidence;$('#ocr-link').href=ref;$('#ocr-link').classList.remove('hidden');$('#ocr-ref').textContent='총장 근거 칸에 이 원본 경로를 함께 기록하세요: '+ref;
}));

async function refreshScreen(){
  if(busyScreen||!state.browser_open)return;busyScreen=true;
  try{const response=await fetch('/api/browser/screenshot');if(!response.ok)return;const blob=await response.blob();if(screenshotUrl)URL.revokeObjectURL(screenshotUrl);screenshotUrl=URL.createObjectURL(blob);$('#browser-screen').src=screenshotUrl;}finally{busyScreen=false;}
}
async function browserAction(body){await api('/browser/action','POST',body);await refreshScreen();}
$('#browser-open').addEventListener('click',()=>act(async()=>{await api('/browser/open','POST');await refresh(true);await refreshScreen();toast('브라우저를 열었습니다. 사이트 이동 후 직접 로그인하세요.');}));
$('#browser-close').addEventListener('click',()=>act(async()=>{await api('/browser/close','POST');await refresh(true);}));
$('#browser-go').addEventListener('click',()=>act(async()=>{try{await api('/browser/navigate','POST',{url:$('#browser-url').value});}finally{await refresh(true);await refreshScreen();}}));
$('#browser-refresh').addEventListener('click',()=>act(refreshScreen));
$('#browser-send').addEventListener('click',()=>act(async()=>{const text=$('#browser-type').value;$('#browser-type').value='';if(text)await browserAction({kind:'type',text});}));
$$('[data-key]').forEach(e=>e.addEventListener('click',()=>act(()=>browserAction({kind:'key',text:e.dataset.key}))));
$$('[data-scroll]').forEach(e=>e.addEventListener('click',()=>act(()=>browserAction({kind:'scroll',delta:Number(e.dataset.scroll)}))));
let pointerStart=null, cropMode=false;
$('#crop-ocr').addEventListener('click',()=>{cropMode=!cropMode;$('#crop-status').textContent=cropMode?'브라우저 화면에서 사이즈표 영역만 드래그하세요. 로그인·계정 정보 영역을 포함하지 마세요.':'OCR 영역 선택을 취소했습니다.';});
function coords(event){const r=$('#browser-screen').getBoundingClientRect();return{x:Math.max(0,Math.min(1200,(event.clientX-r.left)/r.width*1200)),y:Math.max(0,Math.min(850,(event.clientY-r.top)/r.height*850))};}
$('#browser-screen').addEventListener('pointerdown',e=>{e.preventDefault();pointerStart=coords(e);e.target.setPointerCapture(e.pointerId);});
$('#browser-screen').addEventListener('pointerup',e=>act(async()=>{if(!pointerStart)return;const start=pointerStart;pointerStart=null;const end=coords(e);if(cropMode){cropMode=false;$('#crop-status').textContent='선택한 영역을 로컬 OCR로 판독 중…';const data=await api('/browser/ocr-crop','POST',{x:Math.min(start.x,end.x),y:Math.min(start.y,end.y),width:Math.abs(end.x-start.x),height:Math.abs(end.y-start.y)});$('#selected-text').value=data.text+'\n\n원본 근거: /api/evidence/'+data.evidence;$('#crop-status').textContent=data.warning;return;}if(Math.abs(end.x-start.x)+Math.abs(end.y-start.y)>8)await browserAction({kind:'drag',...start,end_x:end.x,end_y:end.y});else await browserAction({kind:'click',...start});}));
$('#get-links').addEventListener('click',()=>act(async()=>{const data=await api('/browser/links');collectedLinks=data.links;$('#links').innerHTML=data.links.map((link,i)=>`<label class="link-item"><input type="checkbox" data-link="${i}"><span>${esc(link.label)}<small>${esc(link.url)}</small></span></label>`).join('');toast(data.links.length+'개 실제 링크를 읽었습니다. 상품 상세 링크만 선택하세요.');}));
$('#get-selection').addEventListener('click',()=>act(async()=>{$('#selected-text').value=(await api('/browser/selection')).text;toast('선택한 텍스트를 읽었습니다. 필요한 근거만 상품에 옮겨 입력하세요.');}));
$('#start-collect').addEventListener('click',()=>act(async()=>{
  if(!$('#collect-men').checked)throw new Error('남성의류 카테고리에서 고른 상품인지 먼저 확인해 주세요.');
  const urls=[...$$('[data-link]:checked').map(e=>collectedLinks[Number(e.dataset.link)].url),...$('#collect-urls').value.split('\n').map(s=>s.trim()).filter(Boolean)];
  const result=await api('/jobs','POST',{urls,limit:Number($('#collect-limit').value),category:$('#collect-category').value,keyword:$('#collect-keyword').value,men_category_confirmed:$('#collect-men').checked});
  await api('/jobs/'+result.id+'/resume','POST');await refresh(true);toast('검토용 초안 수집을 시작했습니다. 완료한 결과는 즉시 저장합니다.');
}));
$('#pause-collect').addEventListener('click',()=>act(async()=>{const data=await api('/jobs/pause','POST');toast(data.message);}));
function renderJobs(){ $('#jobs').innerHTML=state.jobs.map(j=>`<div class="job"><b>작업 #${j.id} · ${{running:'수집 중',paused:'일시정지',completed:'처리 완료'}[j.state]||j.state}</b><p>${j.done} / ${j.total}개 초안 저장 · 실패 ${j.failed}개</p><progress max="${j.total}" value="${j.done+j.failed}"></progress><p>${esc(j.reason)}</p>${j.scope.transport==='chrome_auto'?`<p>Chrome 자동 수집 · 확장의 작업 번호 ${j.id}에서 중지·재개할 수 있습니다.</p>`:''}${j.state!=='running'&&j.done<j.total&&j.scope.transport!=='chrome_auto'?`<button data-resume="${j.id}">재개 · 실패 항목 재시도</button>`:''}<details><summary>항목별 상태</summary>${j.items.map(i=>`<p>${esc(i.url)} · ${esc(i.state)} ${esc(i.error)}</p>`).join('')}</details></div>`).join(''); }
$('#jobs').addEventListener('click',e=>{if(e.target.dataset.resume)act(async()=>{await api('/jobs/'+e.target.dataset.resume+'/resume','POST');await refresh(true);});});
act(()=>refresh());
act(async()=>{const info=await api('/companion/info');$('#companion-folder').value=info.folder;$('#companion-port').textContent=location.port||'8000';});
$('#companion-copy-folder').addEventListener('click',()=>act(async()=>{await navigator.clipboard.writeText($('#companion-folder').value);toast('Chrome의 폴더 선택창에 붙여넣을 경로를 복사했습니다.');}));
$('#companion-open-folder').addEventListener('click',()=>act(async()=>{await api('/companion/open-folder','POST');}));
setInterval(()=>{if(!document.hidden)act(async()=>{await refresh(true);if(currentPane==='collect'&&state.browser_open&&!state.jobs.some(j=>j.state==='running'))await refreshScreen();});},4000);

$('#automatic-pause-all').addEventListener('click',()=>act(async()=>{const data=await api('/jobs/pause','POST');toast(data.message);}));
