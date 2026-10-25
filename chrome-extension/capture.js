// Runs only after the user clicks Capture; standard visible DOM, no site API.
function captureProductPage() {
  const pageUrl = new URL(location.href);
  if (pageUrl.protocol !== 'https:' || !['sinsangmarket.kr', 'www.sinsangmarket.kr'].includes(pageUrl.hostname)) {
    throw new Error('신상마켓의 실제 상품 상세페이지에서 사용하세요.');
  }
  if (pageUrl.username || pageUrl.password || [...pageUrl.searchParams.keys()].some(key => /token|session|auth|password|secret|credential|code|ticket|signature|key/i.test(key))) {
    throw new Error('인증 정보가 포함될 수 있는 URL은 가져오지 않습니다. 로그인 후 일반 상품 URL을 여세요.');
  }
  const visible = element => !!element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden';
  const rawText = document.body?.innerText || '';
  const text = rawText.toLowerCase();
  if (['보안 확인 수행 중', '사람인지 확인하십시오', 'captcha', 'verify you are human', 'access denied', '접근이 제한', '비정상적인 접근'].some(s => text.includes(s))) {
    throw new Error('보안 확인·접근 제한 화면입니다. Chrome에서 직접 확인을 완료한 뒤 상품 상세페이지를 여세요.');
  }
  if ([...document.querySelectorAll('input[type="password"]')].some(visible)) {
    throw new Error('로그인 화면은 가져오지 않습니다. Chrome에서 직접 로그인한 뒤 상품을 여세요.');
  }
  const tables = [...document.querySelectorAll('table')].filter(visible).slice(0, 20).map(table =>
    [...table.rows].slice(0, 60).map(row => [...row.cells].slice(0, 20).map(cell => ({
      text: cell.innerText.trim().slice(0, 500), span: cell.colSpan, rows: cell.rowSpan
    })))
  );
  const chosen = window.getSelection().toString().trim();
  const contexts = [...rawText.matchAll(/숏\s*기장|크롭/g)].slice(0, 8).map(match =>
    rawText.slice(Math.max(0, match.index - 35), match.index + match[0].length + 55).trim());
  const excerpt = chosen || (contexts.length ? '화면의 키워드 주변 문구 · 상품설명인지 확인 필요:\n' + [...new Set(contexts)].join('\n') : '');
  return {url: location.href, title: document.title.slice(0, 300), tables, selection: excerpt.slice(0, 1500)};
}
