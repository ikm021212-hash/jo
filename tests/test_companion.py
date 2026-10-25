import tempfile
import unittest
from fastapi.testclient import TestClient
from smallcloset.app import create_app
from smallcloset.companion import EXTENSION_ID, EXTENSION_ORIGIN, challenge_reason
from test_app import FakeBrowser, HEADERS


def captured(**overrides):
    data={'url':'https://www.sinsangmarket.kr/test-only-companion','title':'테스트 전용 상품',
          'category':'상의','confirmed_product':True,'men_category_confirmed':True,'selection':'테스트 전용 제품설명',
          'tables':[[[{'text':s,'span':1,'rows':1} for s in row] for row in [['사이즈','가슴단면','총장'],['S','60','67'],['M','62','69']]]]}
    data.update(overrides)
    return data


class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=create_app(self.temp.name,FakeBrowser())
        self.context=TestClient(self.app);self.client=self.context.__enter__()
        self.headers={**HEADERS,'Origin':EXTENSION_ORIGIN}
    def tearDown(self):
        self.context.__exit__(None,None,None);self.temp.cleanup()

    def test_manual_chrome_data_is_only_an_unverified_draft(self):
        result=self.client.post('/api/companion/products',json=captured(),headers=self.headers)
        self.assertEqual(result.status_code,200)
        p=self.app.state.store.products()[0]
        self.assertEqual(p['source_type'],'chrome_companion')
        self.assertEqual(p['decision']['status'],'review')
        self.assertEqual([(o['size'],o['length_raw']) for o in p['options']],[('S','67'),('M','69')])
        self.assertFalse(any(o['length_verified'] for o in p['options']))
        self.assertIn('테스트 전용 제품설명',p['capture_note'])

    def test_recapture_updates_and_preserves_memo(self):
        first=self.client.post('/api/companion/products',json=captured(),headers=self.headers).json()['id']
        self.app.state.store.annotate(first,memo='선별 메모',favorite=True)
        second=self.client.post('/api/companion/products',json=captured(title='최신 제목'),headers=self.headers).json()['id']
        self.assertEqual(first,second);p=self.app.state.store.products()[0]
        self.assertEqual(p['name'],'최신 제목');self.assertEqual(p['memo'],'선별 메모');self.assertTrue(p['favorite'])

    def test_credentials_and_non_product_confirmation_rejected(self):
        for values in [dict(confirmed_product=False),dict(men_category_confirmed=False),dict(cookies='TEST ONLY'),dict(password='TEST ONLY'),dict(url='https://www.sinsangmarket.kr/item?session=TEST'),dict(url='https://example.com')]:
            with self.subTest(values=values):
                self.assertEqual(self.client.post('/api/companion/products',json=captured(**values),headers=self.headers).status_code,422)
        self.assertEqual(self.app.state.store.products(),[])

    def test_reported_korean_security_screen_is_not_saved(self):
        response=self.client.post('/api/companion/products',json=captured(title='보안 확인 수행 중'),headers=self.headers)
        self.assertEqual(response.status_code,409);self.assertEqual(self.app.state.store.products(),[])

    def test_only_pinned_extension_origin_gets_cors_permission(self):
        headers={'Origin':EXTENSION_ORIGIN,'Access-Control-Request-Method':'POST',
                 'Access-Control-Request-Headers':'content-type,x-local-client'}
        response=self.client.options('/api/companion/products',headers=headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['access-control-allow-origin'],EXTENSION_ORIGIN)
        self.assertNotIn('access-control-allow-credentials',response.headers)
        bad=self.client.options('/api/companion/products',headers={**headers,'Origin':'https://example.com'})
        self.assertEqual(bad.status_code,403)
        bad=self.client.post('/api/companion/products',json=captured(),headers={**HEADERS,'Origin':'https://example.com'})
        self.assertEqual(bad.status_code,403)

    def test_folder_info_contains_no_session_or_authentication(self):
        response=self.client.get('/api/companion/info').json()
        self.assertEqual(response['extension_id'],EXTENSION_ID)
        self.assertTrue(response['folder'].endswith('chrome-extension'))
        self.assertNotIn('browser-session',str(response))

    def test_crop_cardigan_without_length_is_collected_as_review(self):
        response=self.client.post('/api/companion/products',json=captured(title='크롭 가디건',category='아우터',tables=[]),headers=self.headers)
        self.assertEqual(response.status_code,200)
        p=self.app.state.store.products()[0]
        self.assertEqual(p['category'],'상의');self.assertEqual(p['gender'],'남성')
        self.assertEqual(p['decision']['status'],'review')
        self.assertIn('크롭',p['decision']['reason']);self.assertIn('총장',p['decision']['reason'])

    def test_men_category_confirmation_required_for_collection(self):
        response=self.client.post('/api/jobs',json={'urls':['https://www.sinsangmarket.kr/test-only']},headers=HEADERS)
        self.assertEqual(response.status_code,422)
