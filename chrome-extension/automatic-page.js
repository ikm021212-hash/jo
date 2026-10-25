// All selectors below are HTML/Schema.org semantics, not guessed site classes.
function inspectListingPage() {
  const guard = captureProductPage();
  if (guard.capture_error) return guard;
  const found = new Map();
  for (const anchor of document.querySelectorAll('a[href]')) {
    if (!anchor.getClientRects().length) continue;
    let url;
    try {url = new URL(anchor.href);} catch {continue;}
    if (url.protocol !== 'https:' || !['sinsangmarket.kr','www.sinsangmarket.kr'].includes(url.hostname)) continue;
    if (url.username || url.password || [...url.searchParams.keys()].some(k => (!['keyword','searchkeyword','goodskeyword','productcode','goodscode','itemcode','categorycode'].includes(k.toLowerCase()) && /token|session|auth|password|secret|credential|code|ticket|signature|key/i.test(k)))) continue;
    url.hash = '';
    for (const key of [...url.searchParams.keys()]) if (key.startsWith('utm_') || ['fbclid','gclid'].includes(key)) url.searchParams.delete(key);
    if (url.href === location.href.split('#')[0]) continue;
    let region = anchor;
    for (let depth = 0; depth < 3; depth++) {
      const text = region.innerText.trim();
      const image = region.querySelector('img');
      const links = new Set([...region.querySelectorAll('a[href]')].map(a=>a.href));
      // A real repeated card: image + won price + one destination.
      if (image && /\d[\d,]*\s*원/.test(text) && text.length <= 1000 && links.size <= 1) {
        const previous=found.get(url.href);
        let title=anchor.title || anchor.getAttribute('aria-label') || image.alt || '';
        if(/^(상품|제품)?\s*(이미지|사진|상세보기|보기)$/.test(title.trim()))title='';
        let imageUrl='';try{const imageAddress=new URL(image.currentSrc||image.src,location.href);if(imageAddress.protocol==='https:'){imageAddress.search='';imageAddress.hash='';imageUrl=imageAddress.href;}}catch{}
        found.set(url.href, {url:url.href, label:(previous && previous.label!==text ? '중복 링크 · 가격 확인 필요\n'+previous.label+'\n'+text : text).slice(0,1000),
          name:title.slice(0,300),image_url:imageUrl.slice(0,2048)}); break;
      }
      if (!region.parentElement || region.parentElement === document.body) break;
      region = region.parentElement;
    }
  }
  const next = document.querySelector('a[rel~="next"][href]');
  return {source_url:location.href, candidates:[...found.values()].slice(0,200), next:next?.href || ''};
}

function inspectAutomaticPage() {
  const base = captureProductPage();
  if (base.capture_error) return base;
  const raw = document.body.innerText;
  const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
  const samePath = value => {try {return new URL(value,location.href).pathname.replace(/\/$/,'') === location.pathname.replace(/\/$/,'');} catch {return false;}};
  let roots = [];
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const json = JSON.parse(script.textContent);
      const top = Array.isArray(json) ? json : [json];
      for (const item of top) roots.push(...(Array.isArray(item?.['@graph']) ? item['@graph'] : [item]));
    } catch { /* An invalid JSON-LD block is not usable evidence. */ }
  }
  const typed = (node,type) => node && (Array.isArray(node['@type']) ? node['@type'] : [node['@type']]).some(value=>typeof value==='string' && value.split('/').pop()===type);
  roots = roots.filter(node=>typed(node,'Product') || typed(node,'ProductGroup'));
  const matching = roots.filter(node=>samePath(node.url || node.mainEntityOfPage?.['@id'] || 'INVALID'));
  const root = matching.length === 1 ? matching[0] : roots.length === 1 ? roots[0] : null;
  const h1 = [...document.querySelectorAll('h1')].filter(visible);
  const named = [...document.querySelectorAll('[itemprop="name"]')].filter(visible);
  let name = root?.name && typeof root.name === 'string' ? root.name : named.length === 1 ? named[0].innerText : h1.length === 1 ? h1[0].innerText : document.title;
  const source = root?.name ? '실제 Product JSON-LD name' : named.length === 1 ? '실제 itemprop=name' : h1.length === 1 ? '실제 h1 제목' : '페이지 제목 후보 · 상품명 확인 필요';
  const offers = [];
  const products = root ? (Array.isArray(root.hasVariant) ? root.hasVariant : [root]) : [];
  let supplier = '';
  for (const product of products.slice(0,100)) {
    const entries = Array.isArray(product.offers) ? product.offers : product.offers ? [product.offers] : [];
    for (const offer of entries) {
      if (typed(offer,'AggregateOffer')) continue;
      const item = offer.itemOffered || product;
      const size = typeof item.size === 'string' ? item.size : typeof item.size?.name === 'string' ? item.size.name : '';
      const color = typeof item.color === 'string' ? item.color : '';
      const priceText = typeof offer.price === 'number' || typeof offer.price === 'string' ? String(offer.price) : '';
      const price = /^\d+(?:\.\d+)?$/.test(priceText) ? Number(priceText) : null;
      const display = price === null ? '' : [...raw.matchAll(/(?:\d[\d,]*)\s*원/g)].find(match=>Number(match[0].replace(/[^\d]/g,''))===price)?.[0] || '';
      const seller = offer.seller || product.seller || root.seller;
      if (typeof seller?.name === 'string') supplier = seller.name.slice(0,200);
      offers.push({size:size.slice(0,100),color:color.slice(0,100),price,
        currency:String(offer.priceCurrency || '').slice(0,20),availability:String(offer.availability || '').slice(0,300),visible_price_text:display});
    }
  }
  const tables = [...document.querySelectorAll('table')].filter(visible).slice(0,20);
  const candidates = [...document.images].filter(img=>visible(img) && img.complete && img.naturalWidth >= 100 && img.naturalHeight >= 70);
  const imageValue = root?.image;
  const preferred = typeof imageValue === 'string' ? imageValue : Array.isArray(imageValue) ? imageValue[0]?.url || imageValue[0]?.contentUrl || imageValue[0] : imageValue?.url || imageValue?.contentUrl;
  const og = document.querySelector('meta[property="og:image"]')?.content;
  const mainImages=candidates.filter(img=>img.closest('main') && !/사이즈|실측|총장|기장|size/i.test(img.alt));
  const primary = candidates.find(img=>[preferred,og].some(url=>{
    if(typeof url!=='string')return false;try{return new URL(url,location.href).href===img.currentSrc;}catch{return false;}
  })) || (mainImages.length===1?mainImages[0]:undefined);
  const charts = candidates.filter(img=>/사이즈|실측|총장|기장|size/i.test(img.alt)).slice(0,2);
  const fallback = charts.length ? charts : candidates.filter(img=>img!==primary).slice(-2);
  const siteCategory=typeof root?.category==='string'?root.category:Array.isArray(root?.category)?root.category.filter(value=>typeof value==='string').join(' > '):'';
  return {...base,name:String(name || '').trim().slice(0,300),name_source:source,site_category:siteCategory.slice(0,200),supplier,offers:offers.slice(0,200),
    table_units:tables.map(table=>(table.caption?.innerText || '').slice(0,100)),
    photo:primary?.currentSrc || '', charts:fallback.map(img=>img.currentSrc), detail_note:''};
}

function openObservedDetail(label) {
  const guard = captureProductPage();
  if (guard.capture_error) return guard;
  const normalize = text => text.replace(/\s+/g,'').replace(/보기$/,'');
  let elements = [...document.querySelectorAll('button,a,[role="tab"],[role="button"],summary')]
    .filter(e=>e.getClientRects().length && normalize(e.innerText)===normalize(label));
  if (!elements.length) elements = [...document.body.querySelectorAll('*')]
    .filter(e=>!e.children.length && e.getClientRects().length && normalize(e.textContent)===normalize(label));
  if (elements.length !== 1) return {opened:false};
  const element=elements[0];
  if (element.tagName === 'A' && element.href && !element.href.startsWith('javascript:')) {
    const target=new URL(element.href);
    if (target.protocol==='https:' && ['sinsangmarket.kr','www.sinsangmarket.kr'].includes(target.hostname) && target.href.split('#')[0]!==location.href.split('#')[0]) return {opened:true,href:target.href};
  }
  element.click(); return {opened:true};
}

function readImagePixels(source) {
  const guard=captureProductPage();
  if (guard.capture_error) return guard;
  const image=[...document.images].find(img=>img.currentSrc===source);
  if (!image || !image.complete || !image.naturalWidth) return {error:'이미지 로딩 미완료'};
  if (image.naturalWidth*image.naturalHeight<=4000000) {
    try {
      const canvas=document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
      canvas.getContext('2d').drawImage(image,0,0);
      const data=canvas.toDataURL('image/png');
      if (data.length<=12000000) return {data};
    } catch { /* Cross-origin pixels may only be read via an authorized tab crop. */ }
  }
  image.scrollIntoView({block:'center',inline:'nearest'});
  const rect=image.getBoundingClientRect();
  if (rect.left<0 || rect.top<0 || rect.right>innerWidth || rect.bottom>innerHeight) return {error:'이미지가 화면보다 커 전체 영역을 확인할 수 없음'};
  for (const [x,y] of [[rect.left+2,rect.top+2],[rect.right-2,rect.top+2],[rect.left+2,rect.bottom-2],[rect.right-2,rect.bottom-2],[rect.left+rect.width/2,rect.top+rect.height/2]]) {
    if (document.elementFromPoint(x,y)!==image) return {error:'다른 화면 요소가 이미지 영역을 가려 캡처하지 않음'};
  }
  return {rect:{x:rect.left,y:rect.top,width:rect.width,height:rect.height,viewportWidth:innerWidth,viewportHeight:innerHeight}};
}
