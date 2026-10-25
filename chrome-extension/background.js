importScripts('capture.js');

async function captureCurrentProduct(message) {
  if (message.confirmed_product !== true) throw new Error('상품 상세페이지임을 확인해 주세요.');
  if (message.men_category_confirmed !== true) throw new Error('남성의류 카테고리에서 고른 상품만 가져올 수 있습니다.');
  const port = Number(message.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('프로그램 포트가 올바르지 않습니다.');
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tab?.id) throw new Error('현재 상품 탭을 찾을 수 없습니다.');
  const url = new URL(tab.url || '');
  if (url.protocol !== 'https:' || !['sinsangmarket.kr', 'www.sinsangmarket.kr'].includes(url.hostname)) {
    throw new Error('신상마켓 상품 탭을 선택한 뒤 확장프로그램을 여세요.');
  }
  const results = await chrome.scripting.executeScript({target: {tabId: tab.id}, func: captureProductPage});
  const page = results[0]?.result;
  if (!page) throw new Error('현재 페이지를 읽을 수 없습니다. 페이지 로딩 후 다시 시도하세요.');
  const response = await fetch(`http://127.0.0.1:${port}/api/companion/products`, {
    method: 'POST', headers: {'Content-Type': 'application/json', 'X-Local-Client': 'smallcloset'},
    body: JSON.stringify({...page, category: message.category || '미분류', confirmed_product: true, men_category_confirmed: true}),
    signal: AbortSignal.timeout(15000)
  }).catch(() => {throw new Error('작은옷장에 연결할 수 없습니다. START-WINDOWS.bat 실행 여부와 프로그램 포트를 확인하세요.');});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '가져올 수 없는 데이터입니다.');
  await chrome.storage.local.set({port, category: message.category || '미분류'});
  return data;
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || message?.type !== 'capture-current-product') return;
  captureCurrentProduct(message).then(data => respond({ok: true, ...data}), error => respond({ok: false, error: error.message}));
  return true;
});
