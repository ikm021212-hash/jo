'use strict';
const $ = selector => document.querySelector(selector);
chrome.storage.local.get({port: 8000, category: '미분류'}).then(saved => {
  $('#port').value = saved.port; $('#category').value = saved.category;
});
$('#confirmed').addEventListener('change', () => {$('#capture').disabled = !$('#confirmed').checked;});
$('#capture').addEventListener('click', async () => {
  $('#capture').disabled = true; $('#status').textContent = '현재 상품 근거를 가져오는 중…';
  try {
    const result = await chrome.runtime.sendMessage({type:'capture-current-product', port:Number($('#port').value),
      category:$('#category').value, confirmed_product:$('#confirmed').checked, men_category_confirmed:$('#confirmed').checked});
    if (!result?.ok) throw new Error(result?.error || '확장프로그램 처리 실패');
    $('#status').textContent = '검토용 초안을 저장했습니다.\n작은옷장 화면에서 가격·총장·재고 근거를 확인하세요.';
  } catch (error) {$('#status').textContent = error.message;}
  finally {$('#capture').disabled = !$('#confirmed').checked;}
});
