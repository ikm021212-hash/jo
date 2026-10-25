import copy
import tempfile
import unittest
from fastapi.testclient import TestClient
from smallcloset.app import create_app
from smallcloset.automatic import build_automatic_product, explicit_minimum
from smallcloset.domain import DEFAULT_RULES, evaluate
from test_app import HEADERS, FakeBrowser


def observed(**changes):
    cells=lambda row:[{'text':str(value),'span':1,'rows':1} for value in row]
    data={'url':'https://www.sinsangmarket.kr/test-auto-1','title':'실제 페이지 제목',
          'name':'크롭 후드집업','name_source':'실제 Product JSON-LD name','selection':'제품설명',
          'category':'상의','confirmed_product':True,'men_category_confirmed':True,
          'tables':[[cells(['사이즈','가슴단면','총장(cm)']),cells(['S',60,67]),cells(['M',62,69])]],
          'table_units':[''], 'offers':[
              {'size':'S','color':'검정','price':23800,'currency':'KRW','availability':'https://schema.org/InStock','visible_price_text':'23,800원'},
              {'size':'M','color':'검정','price':23000,'currency':'KRW','availability':'https://schema.org/InStock','visible_price_text':'23,000원'}]}
    data.update(changes);return data


class InterpretationTests(unittest.TestCase):
    def test_same_size_offer_and_explicit_cm_table(self):
        p=build_automatic_product(observed(),'아우터');result=evaluate(p,DEFAULT_RULES)
        self.assertEqual(p['category'],'상의');self.assertEqual(result['matching_options'],['S / 검정'])
        self.assertIn('Product/Offer',p['options'][0]['price_evidence'])

    def test_no_mix_of_cheap_long_and_expensive_short(self):
        data=observed();data['offers'][0].update(price=25000,visible_price_text='25,000원')
        self.assertEqual(evaluate(build_automatic_product(data,'상의'),DEFAULT_RULES)['status'],'fail')

    def test_no_size_no_unit_no_display_or_no_stock_is_not_passed(self):
        for kind in ['size','unit','display','stock']:
            data=observed();data['offers']=data['offers'][:1]
            if kind=='size':data['offers'][0]['size']=''
            if kind=='unit':data['tables'][0][0][2]['text']='총장'
            if kind=='display':data['offers'][0]['visible_price_text']=''
            if kind=='stock':data['offers'][0]['availability']=''
            with self.subTest(kind=kind):self.assertEqual(evaluate(build_automatic_product(data,'상의'),DEFAULT_RULES)['status'],'review')

    def test_conflicting_tables_require_review(self):
        data=observed();data['offers']=data['offers'][:1]
        second=copy.deepcopy(data['tables'][0]);second[1][2]['text']='69';data['tables'].append(second)
        p=build_automatic_product(data,'상의')
        self.assertFalse(p['options'][0]['length_verified']);self.assertEqual(evaluate(p,DEFAULT_RULES)['status'],'review')

    def test_explicit_minimum_only(self):
        self.assertEqual(explicit_minimum('상품 최저 60,000원부터'),60000)
        for text in ['상품 60,000원','최저 60,000원 배송 3,000원','중복 링크 최저 60,000원']:
            self.assertIsNone(explicit_minimum(text))


class AutomaticAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=create_app(self.temp.name,FakeBrowser())
        self.context=TestClient(self.app);self.client=self.context.__enter__()
    def tearDown(self):self.context.__exit__(None,None,None);self.temp.cleanup()
    def post(self,path,body):return self.client.post('/api/companion/auto'+path,json=body,headers=HEADERS)
    def start(self,count=2,**changes):
        data={'source_url':'https://www.sinsangmarket.kr/test-men-list','men_category_confirmed':True,'category':'상의',
              'candidates':[{'url':f'https://www.sinsangmarket.kr/test-auto-{i}','label':'상품 23,800원'} for i in range(1,count+1)]}
        data.update(changes);result=self.post('/start',data);self.assertEqual(result.status_code,200,result.text)
        return result.json()['job_id']

    def test_twenty_default_limit_dedup_and_resume(self):
        job=self.start(25);self.assertEqual(self.app.state.store.chrome_job(job)['total'],20)
        first=self.post(f'/{job}/next',{}).json()['item']
        self.assertEqual(first['id'],self.post(f'/{job}/next',{}).json()['item']['id'])
        self.post(f'/{job}/pause',{'reason':'사용자 중지'})
        self.assertIsNone(self.post(f'/{job}/next',{}).json()['item'])
        self.post(f'/{job}/resume',{})
        self.assertEqual(first['id'],self.post(f'/{job}/next',{}).json()['item']['id'])

    def test_result_is_saved_and_not_duplicated(self):
        job=self.start(1);item=self.post(f'/{job}/next',{}).json()['item']
        body={'item_id':item['id'],'page':observed()}
        result=self.post(f'/{job}/result',body);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['decision']['matching_options'],['S / 검정'])
        self.post(f'/{job}/result',body)
        self.assertEqual(len(self.app.state.store.products()),1)
        self.post(f'/{job}/next',{})
        self.assertEqual(self.app.state.store.chrome_job(job)['state'],'completed')

    def test_list_minimum_prefilter_does_not_visit_detail(self):
        job=self.start(1,candidates=[{'url':'https://www.sinsangmarket.kr/test-expensive','label':'최저 60,000원부터'}])
        self.assertTrue(self.post(f'/{job}/next',{}).json()['filtered'])
        p=self.app.state.store.products()[0]
        self.assertEqual(p['decision']['status'],'fail');self.assertEqual(p['listing_min_price'],60000)

    def test_security_screen_pauses_and_keeps_previous_results(self):
        job=self.start(2);item=self.post(f'/{job}/next',{}).json()['item']
        self.post(f'/{job}/result',{'item_id':item['id'],'page':observed()})
        second=self.post(f'/{job}/next',{}).json()['item']
        result=self.post(f'/{job}/result',{'item_id':second['id'],'page':observed(title='보안 확인 수행 중')})
        self.assertEqual(result.status_code,409)
        self.assertEqual(self.app.state.store.chrome_job(job)['state'],'paused')
        self.assertEqual(len(self.app.state.store.products()),1)

    def test_image_upload_is_local_and_reloads(self):
        from PIL import Image
        import io
        output=io.BytesIO();Image.new('RGB',(50,70),'green').save(output,format='PNG')
        saved=self.client.post('/api/images',content=output.getvalue(),headers=HEADERS)
        self.assertEqual(saved.status_code,200)
        r=self.client.get(saved.json()['url']);self.assertEqual(r.status_code,200)
        self.assertTrue(r.content.startswith(b'\x89PNG'))
