import json
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, tag
from django.urls import reverse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.selenium_helpers import get_chrome_options, login_via_browser

from . import views
from .models import Feedback


class FeedbackAccessTests(TestCase):
    """The inbox and its APIs are for staff only."""

    def setUp(self):
        self.fb = Feedback.objects.create(message='Secret note', is_read=False)
        self.guest = User.objects.create_user('guest', password='pw')

    def _bulk(self, action='delete'):
        return self.client.post(reverse('bulk_feedback_action'),
                                json.dumps({'feedback_ids': [self.fb.id], 'action': action}),
                                content_type='application/json')

    def test_anonymous_is_sent_to_login(self):
        r = self.client.get(reverse('view_feedback'))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('login'), r['Location'])
        self.assertEqual(self.client.get(reverse('feedback_list')).status_code, 403)
        self.assertEqual(self._bulk().status_code, 403)
        self.assertTrue(Feedback.objects.filter(id=self.fb.id).exists())

    def test_non_staff_user_is_refused(self):
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(reverse('view_feedback')).status_code, 302)
        self.assertEqual(self.client.get(reverse('feedback_list')).status_code, 403)
        self.assertEqual(self._bulk('mark_read').status_code, 403)
        self.fb.refresh_from_db()
        self.assertFalse(self.fb.is_read)

    def _navbar(self, user):
        request = RequestFactory().get('/wifi/')
        request.user = user
        request.session = {}
        return render_to_string('base.html', request=request)

    def test_avatar_menu_offers_inbox_to_staff_only(self):
        html = self._navbar(self.guest)
        self.assertIn('id="user-menu-button"', html)
        self.assertIn('id="logout-button"', html)
        self.assertNotIn('id="inbox-link"', html)
        self.assertNotIn('class="badge"', html)
        staff = User.objects.create_user('owner', password='pw', is_staff=True, first_name='Stephen')
        html = self._navbar(staff)
        self.assertIn('id="inbox-link"', html)
        self.assertIn('<span class="hub-ini">S</span>', html)
        self.assertIn('>1</span>', html)

    def test_unread_count_hidden_from_non_staff(self):
        r = self.client.get(reverse('get_unread_feedback_count'))
        self.assertEqual(r.json()['unread_feedback_count'], 0)


class FeedbackInboxTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('owner', password='pw', is_staff=True)
        self.client.force_login(self.staff)
        self.old = Feedback.objects.create(message='Older message', is_read=True, page_url='http://hub/')
        self.new = Feedback.objects.create(message='Newer message', page_url='http://hub/nowhere/',
                                           stay='the Henderson stay')

    def test_inbox_page_embeds_messages(self):
        r = self.client.get(reverse('view_feedback'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="fbx-data"')
        self.assertContains(r, 'Newer message')

    def test_list_is_newest_first_with_page_and_stay(self):
        items = self.client.get(reverse('feedback_list')).json()['items']
        self.assertEqual([i['id'] for i in items], [self.new.id, self.old.id])
        self.assertEqual(items[0]['stay'], 'the Henderson stay')
        self.assertFalse(items[0]['is_read'])
        self.assertEqual(items[1]['page']['title'], 'Home')
        self.assertEqual(items[0]['page']['title'], '/nowhere/')

    def test_page_uses_app_tile_title(self):
        page = views._page('http://hub/feedback/')
        self.assertEqual(page['title'], '/feedback/')  # feedback has no tile
        with mock.patch.object(views, 'plugins') as plugins:
            spec = mock.Mock(urls='x.urls', prefix='wifi/',
                             tiles=[mock.Mock(title='WiFi', icon='')])
            plugins.return_value = [spec]
            self.assertEqual(views._page('http://hub/wifi/qr/')['title'], 'WiFi')

    def test_bulk_actions(self):
        url = reverse('bulk_feedback_action')

        def post(action, ids):
            return self.client.post(url, json.dumps({'feedback_ids': ids, 'action': action}),
                                    content_type='application/json')

        self.assertEqual(post('mark_read', [self.new.id]).status_code, 200)
        self.new.refresh_from_db()
        self.assertTrue(self.new.is_read)
        post('mark_unread', [self.new.id, self.old.id])
        self.assertEqual(Feedback.objects.filter(is_read=False).count(), 2)
        self.assertEqual(post('explode', [self.new.id]).status_code, 400)
        self.assertEqual(post('delete', []).status_code, 400)
        post('delete', [self.old.id])
        self.assertEqual(list(Feedback.objects.values_list('id', flat=True)), [self.new.id])

    def test_bulk_action_requires_post(self):
        self.assertEqual(self.client.get(reverse('bulk_feedback_action')).status_code, 405)


class SubmitFeedbackTests(TestCase):
    def _submit(self, **data):
        return self.client.post(reverse('submit_feedback'), {'page_url': 'http://hub/', **data})

    @mock.patch.object(views, 'current_stay', return_value={'guest': 'Henderson', 'owner': False})
    def test_records_guest_stay(self, _):
        self.assertTrue(self._submit(message=' Hot tub is cold ').json()['success'])
        fb = Feedback.objects.get()
        self.assertEqual(fb.message, 'Hot tub is cold')
        self.assertEqual(fb.stay, 'the Henderson stay')
        self.assertEqual(fb.page_url, 'http://hub/')

    @mock.patch.object(views, 'current_stay', return_value={'guest': 'Stephen', 'owner': True})
    def test_records_owner_visit(self, _):
        self._submit(message='hi')
        self.assertEqual(Feedback.objects.get().stay, 'an owner visit')

    @mock.patch.object(views, 'current_stay', side_effect=RuntimeError('stays down'))
    def test_stay_lookup_failure_still_saves(self, _):
        self._submit(message='hi')
        self.assertEqual(Feedback.objects.get().stay, '')

    @mock.patch.object(views, 'current_stay', return_value=None)
    def test_rejects_empty_message_and_get(self, _):
        self.assertEqual(self._submit(message='   ').status_code, 400)
        self.assertEqual(self.client.get(reverse('submit_feedback')).status_code, 405)
        self.assertFalse(Feedback.objects.exists())


@tag('selenium')
class FeedbackInboxSeleniumTest(StaticLiveServerTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.browser = webdriver.Chrome(options=get_chrome_options())
        cls.browser.set_window_size(1920, 1080)

    @classmethod
    def tearDownClass(cls):
        cls.browser.quit()
        super().tearDownClass()

    def setUp(self):
        User.objects.create_user(username='testuser', password='testpassword', is_staff=True)
        self.first = Feedback.objects.create(message='The hot tub cover is stuck', page_url='/')
        self.second = Feedback.objects.create(message='Webcam is frozen', page_url='/', is_read=True)
        self.browser.get('about:blank')
        self.browser.delete_all_cookies()
        login_via_browser(self.browser, self.live_server_url)
        self.browser.get(self.live_server_url + reverse('view_feedback'))
        self.wait = WebDriverWait(self.browser, 20)

    def _row(self, fb):
        try:
            return self.wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, f'.fbx-it[data-id="{fb.id}"]')))
        except Exception:
            from tests.selenium_helpers import dump_browser
            dump_browser(self.browser, 'inbox-row')
            raise

    def test_opening_a_message_marks_it_read(self):
        # Starts on the Unread filter, so only the unread message is listed.
        self.assertEqual(len(self.browser.find_elements(By.CSS_SELECTOR, '.fbx-it')), 1)
        self._row(self.first).click()
        self.wait.until(EC.text_to_be_present_in_element(
            (By.CSS_SELECTOR, '.fbx-msg'), 'The hot tub cover is stuck'))
        self.wait.until(lambda d: Feedback.objects.get(id=self.first.id).is_read)
        self.assertEqual(self.browser.find_element(By.ID, 'count-unread').text, '0')

    def test_delete_needs_two_taps(self):
        self.browser.find_element(By.CSS_SELECTOR, '.fbx-chip[data-filter="all"]').click()
        self._row(self.second).click()
        delete = self.wait.until(EC.element_to_be_clickable((By.ID, 'detail-delete')))
        delete.click()
        self.assertIn('Tap again', delete.text)
        self.assertTrue(Feedback.objects.filter(id=self.second.id).exists())
        delete.click()
        self.wait.until(lambda d: not Feedback.objects.filter(id=self.second.id).exists())
        self.wait.until(EC.invisibility_of_element_located(
            (By.CSS_SELECTOR, f'.fbx-it[data-id="{self.second.id}"]')))
