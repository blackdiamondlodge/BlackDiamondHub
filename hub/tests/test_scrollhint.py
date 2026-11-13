from django.test import tag
from selenium.webdriver.support.ui import WebDriverWait

from tests.selenium_helpers import SeleniumTestCase, wait_for_paint

LIST = """
const box = document.createElement('div');
box.id = 'sh-box';
box.style.cssText = 'position:fixed;left:100px;top:100px;width:400px;height:300px;overflow-y:auto';
if (arguments[0]) box.dataset.scrollHint = arguments[0];
box.innerHTML = '<div style="height:1200px"></div>';
document.body.appendChild(box);
window.hubScrollHint.refresh();
"""


@tag("selenium")
class ScrollHintTest(SeleniumTestCase):
    """base.html's shared chevron on scroll containers it finds by itself."""

    def setUp(self):
        super().setUp()
        self.browser.get(f"{self.live_server_url}/accounts/login/")
        wait_for_paint(self.browser)

    def hint_on(self):
        return self.browser.execute_script(
            "const h = document.getElementById('sh-box').parentNode.querySelector(':scope > .hub-scroll-hint');"
            "return h ? h.classList.contains('on') : null")

    def test_inner_scroller_gets_a_chevron_until_the_end(self):
        b = self.browser
        b.execute_script(LIST, None)
        self.assertEqual(b.execute_script("const e = document.getElementById('sh-box'); return e.offsetWidth - e.clientWidth"), 0)
        WebDriverWait(b, 5).until(lambda d: self.hint_on() is True)
        b.execute_script("const e = document.getElementById('sh-box'); e.scrollTop = e.scrollHeight")
        WebDriverWait(b, 5).until(lambda d: self.hint_on() is False)

    def test_chevron_hides_while_something_covers_the_scroller(self):
        b = self.browser
        b.execute_script(LIST, None)
        WebDriverWait(b, 5).until(lambda d: self.hint_on() is True)
        b.execute_script(
            "const o = document.createElement('div'); o.id = 'sh-cover';"
            "o.style.cssText = 'position:fixed;inset:0;z-index:999;background:#000';"
            "document.body.appendChild(o)")
        WebDriverWait(b, 5).until(lambda d: self.hint_on() is False)
        b.execute_script("document.getElementById('sh-cover').remove()")
        WebDriverWait(b, 5).until(lambda d: self.hint_on() is True)

    def test_opt_out(self):
        self.browser.execute_script(LIST, "off")
        self.assertIsNone(self.hint_on())
