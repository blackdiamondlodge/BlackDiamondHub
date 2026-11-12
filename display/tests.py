import io
import os
import shutil
import tempfile
from datetime import date, timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from hub_settings import store
from hub_settings.models import AppSetting
from .models import SaverPhoto, UploadLink
from .options import DEFAULT_STARTS
from .schedule import is_night, parse_hhmm
from .season import parse_mmdd, resolve
from .stats import MINUS, collect, stat, sun_times

STARTS = dict(DEFAULT_STARTS)  # winter 11-21, spring 03-15, summer 06-01, fall 09-15


class FakeState(dict):
    def set(self, key, value):
        self[key] = value


class SeasonTests(TestCase):
    def test_by_date(self):
        self.assertEqual(resolve(date(2026, 1, 5), STARTS, use_lifts=False), "winter")
        self.assertEqual(resolve(date(2026, 3, 15), STARTS, use_lifts=False), "spring")
        self.assertEqual(resolve(date(2026, 7, 1), STARTS, use_lifts=False), "summer")
        self.assertEqual(resolve(date(2026, 11, 20), STARTS, use_lifts=False), "fall")
        self.assertEqual(resolve(date(2026, 11, 21), STARTS, use_lifts=False), "winter")

    def test_lifts_bring_winter_forward_inside_window(self):
        state = FakeState()
        self.assertEqual(resolve(date(2026, 11, 1), STARTS, lifts_open=3, state=state), "winter")
        self.assertEqual(state["lifts_opened"], "2026-11-01")

    def test_lifts_ignored_outside_window(self):
        state = FakeState()
        self.assertEqual(resolve(date(2026, 10, 1), STARTS, lifts_open=3, state=state), "fall")
        self.assertNotIn("lifts_opened", state)

    def test_remembered_opening_sticks(self):
        state = FakeState(lifts_opened="2026-11-01")
        self.assertEqual(resolve(date(2026, 11, 5), STARTS, lifts_open=None, state=state), "winter")

    def test_last_years_opening_is_ignored(self):
        state = FakeState(lifts_opened="2025-11-01")
        self.assertEqual(resolve(date(2026, 11, 5), STARTS, lifts_open=0, state=state), "fall")

    def test_lifts_off(self):
        self.assertEqual(resolve(date(2026, 11, 1), STARTS, lifts_open=3, use_lifts=False), "fall")

    def test_parse_mmdd(self):
        self.assertEqual(parse_mmdd("02-29"), (2, 29))
        for bad in ("11/21", "1-21", "13-01", "02-30", "", "abc"):
            with self.assertRaisesMessage(ValueError, "Use MM-DD"):
                parse_mmdd(bad)


DATA = {
    "resort": {
        "temperatures": [
            {"name": "Top of the World", "elevation_m": 2080, "c": -6.4},
            {"name": "Valley", "elevation_m": 1255, "c": 0.4},
        ],
        "new_snow": [{"period": "48 Hr", "cm": 38}],
    },
    "lifts": {"lifts_open": 0, "lifts_total": 13, "trails_open": 112, "trails_total": 138},
}


class StatTests(TestCase):
    def test_formats(self):
        today = date(2026, 11, 11)
        self.assertEqual(stat("temp_top", DATA, today, STARTS), {"label": "Up top", "value": f"{MINUS}6°C"})
        self.assertEqual(stat("temp_village", DATA, today, STARTS)["value"], "0°C")
        self.assertEqual(stat("new_snow", DATA, today, STARTS)["value"], "38 cm")
        self.assertEqual(stat("runs_open", DATA, today, STARTS)["value"], "112 of 138")
        self.assertEqual(stat("days_until_lifts", DATA, today, STARTS)["value"], "10 days")

    def test_missing_data_is_skipped(self):
        keys = ["temp_top", "none", "base", "wind_top", "groomed"]
        self.assertEqual(collect(keys, {}, date(2026, 11, 11), STARTS), [])

    def test_sun_times_are_plausible(self):
        rise, sets = sun_times(date(2026, 6, 21), 50.884, -119.885)
        # Sun Peaks summer solstice: about 4:45 and 21:15 local (UTC-7).
        self.assertEqual(((rise.hour - 7) % 24, rise.minute // 15), (4, 3))
        self.assertEqual(((sets.hour - 7) % 24, sets.minute // 15), (21, 1))


@override_settings(HUB_PLUGINS=settings.HUB_PLUGINS)
class ViewTests(TestCase):
    def setUp(self):
        store.clear()
        self.addCleanup(store.clear)
        User = get_user_model()
        self.staff = User.objects.create_user("staff", password="pw", is_staff=True)
        self.guest = User.objects.create_user("guest", password="pw")
        for target, value in (("display.views.gather", DATA), ("display.views._cams", [
            {"camera_name": "Sunburst Express", "slug": "sunburst", "image_url": "http://x/s.jpg"},
            {"camera_name": "Village", "slug": "village", "image_url": "http://x/v.jpg"},
        ])):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_saver_api(self):
        body = self.client.get(reverse("display_saver_api"), {"season": "winter"}).json()
        self.assertEqual(body["season"], "winter")
        self.assertEqual(body["sources"], ["stock"])
        self.assertEqual([s["label"] for s in body["stats"]], ["Up top", "At the lodge", "New snow, 48h", "Runs open"])

    def test_saver_api_cam(self):
        AppSetting.objects.create(app_id="display", key="source_summer", value="mix")
        body = self.client.get(reverse("display_saver_api"), {"season": "summer"}).json()
        self.assertEqual(body["sources"], ["stock", "cam"])
        self.assertEqual(body["cam"]["name"], "Sunburst Express")

    def test_settings_staff_only(self):
        url = reverse("display_settings")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_settings_page_and_nav(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("display_settings"))
        self.assertContains(response, "Screensaver, background &amp; schedule")
        self.assertContains(response, f'href="{reverse("display_settings")}"')
        self.assertContains(response, 'name="slot_fall_4"')

    def test_generic_app_page_redirects(self):
        self.client.force_login(self.staff)
        response = self.client.get("/settings/app/display/")
        self.assertRedirects(response, reverse("display_settings"), fetch_redirect_response=False)

    def form(self, **overrides):
        self.client.force_login(self.staff)
        page = self.client.get(reverse("display_settings"))
        data = {}
        for s in page.context["seasons"]:
            data[s["start_key"]] = s["start"]
            data[f"source_{s['id']}"] = s["source"]
            data.update({slot["key"]: slot["value"] for slot in s["slots"]})
        data.update(idle_minutes="10", burn_in="on", winter_on_lifts="on", rotate_minutes="3", cam="", tab="fall",
                    night="on", night_from="23:00", night_until="06:00")
        data.update(overrides)
        return data

    def test_save(self):
        response = self.client.post(reverse("display_settings"), self.form(winter_start="11-1", idle_minutes="15"))
        self.assertEqual(response.status_code, 400)  # 11-1 isn't MM-DD
        self.assertContains(response, "Use MM-DD", status_code=400)

        response = self.client.post(reverse("display_settings"), self.form(winter_start="11-01", idle_minutes="15"))
        self.assertRedirects(response, reverse("display_settings") + "?saved=1&season=fall",
                             fetch_redirect_response=False)
        saved = store.saved("display")
        self.assertEqual(saved["winter_start"], "11-01")
        self.assertEqual(saved["idle_minutes"], 15)
        self.assertNotIn("burn_in", saved)  # unchanged defaults stay unsaved

    def test_night_times(self):
        response = self.client.post(reverse("display_settings"), self.form(night_from="25:00"))
        self.assertContains(response, "Use HH:MM", status_code=400)

        self.client.post(reverse("display_settings"), self.form(night_from="22:30", night_until="7:00"))
        saved = store.saved("display")
        self.assertEqual((saved["night_from"], saved["night_until"]), ("22:30", "07:00"))

        with mock.patch("display.views.lodge_minute", return_value=23 * 60):
            self.assertTrue(self.client.get(reverse("display_schedule_api")).json()["dark"])
        with mock.patch("display.views.lodge_minute", return_value=12 * 60):
            body = self.client.get(reverse("display_schedule_api")).json()
        self.assertEqual(body, {"enabled": True, "from": "22:30", "until": "07:00", "dark": False})

        self.client.post(reverse("display_settings"), {k: v for k, v in self.form().items() if k != "night"})
        body = self.client.get(reverse("display_schedule_api")).json()
        self.assertEqual(body, {"enabled": False, "from": None, "until": None, "dark": False})


class ScheduleTests(TestCase):
    def test_is_night_wraps_midnight(self):
        night = (23 * 60, 6 * 60)
        self.assertTrue(is_night(23 * 60, *night))
        self.assertTrue(is_night(3 * 60, *night))
        self.assertFalse(is_night(6 * 60, *night))
        self.assertFalse(is_night(12 * 60, *night))
        self.assertTrue(is_night(14 * 60, 13 * 60, 15 * 60))
        self.assertFalse(is_night(0, 0, 0))  # same start and end: never

    def test_parse_hhmm(self):
        self.assertEqual(parse_hhmm(" 6:05 "), 365)
        for bad in ("", "6", "24:00", "12:60", "ab:cd"):
            with self.assertRaises(ValueError):
                parse_hhmm(bad)


def jpeg(size=(800, 600), orientation=None, name="p.jpg", taken=None):
    img = Image.new("RGB", size, (200, 30, 30))
    buf = io.BytesIO()
    exif = img.getexif()
    if orientation:
        exif[0x0112] = orientation
    if taken:
        exif[0x8769] = {36867: taken}  # Exif IFD: DateTimeOriginal
    exif[0x010F] = "SecretCam"  # Make: must not survive processing
    img.save(buf, "JPEG", exif=exif)
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


class PhotoTests(TestCase):
    def setUp(self):
        self.addCleanup(store.clear)
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        storage = FileSystemStorage(root, base_url="/media/apps/display/")
        for name in ("image", "thumb"):
            patcher = mock.patch.object(SaverPhoto._meta.get_field(name), "storage", storage)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = root
        User = get_user_model()
        self.staff = User.objects.create_user("staff", password="pw", is_staff=True)
        self.guest = User.objects.create_user("guest", password="pw")
        self.client.force_login(self.staff)
        patcher = mock.patch("display.views.gather", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def link(self):
        return self.client.post(reverse("display_upload_link")).json()

    def test_phone_upload_flow(self):
        link = self.link()
        self.assertIn("<svg", link["qr"])
        self.assertTrue(link["url"].endswith(f"/display/upload/{link['key']}/"))
        phone = Client()
        page = phone.get(reverse("display_upload", args=[link["key"]]))
        self.assertContains(page, "Choose photos")
        self.assertEqual(page["Cache-Control"], "no-store")
        response = phone.post(reverse("display_upload_photo", args=[link["key"]]),
                              {"photo": jpeg(), "seasons": "summer"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["photos"][0]["tag"], "Summer")
        status = self.client.get(reverse("display_photos"), {"link": link["key"]}).json()
        self.assertEqual(status["link"]["arrived"], 1)
        self.assertTrue(status["link"]["claimed"])
        self.assertGreater(status["link"]["seconds"], 25 * 60)  # claiming extends the code

        other = Client()
        self.assertEqual(other.get(reverse("display_upload", args=[link["key"]])).status_code, 403)
        self.assertEqual(other.post(reverse("display_upload_photo", args=[link["key"]]),
                                    {"photo": jpeg()}).status_code, 403)

    def test_upload_link_errors(self):
        phone = Client()
        self.assertEqual(phone.get(reverse("display_upload", args=["nope"])).status_code, 404)
        link = UploadLink.objects.create()
        # Posting without opening the page (no claim) is refused.
        self.assertEqual(phone.post(reverse("display_upload_photo", args=[link.key]),
                                    {"photo": jpeg()}).status_code, 403)
        UploadLink.objects.filter(pk=link.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertContains(phone.get(reverse("display_upload", args=[link.key])), "expired", status_code=410)

    def test_processing(self):
        response = self.client.post(reverse("display_photo_add"), {"photo": jpeg((4000, 1000), orientation=6)})
        self.assertEqual(response.status_code, 200)
        photo = SaverPhoto.objects.get()
        self.assertEqual(photo.seasons, [])
        with Image.open(photo.image.path) as img:
            self.assertEqual(img.size, (640, 2560))  # rotated upright, then fit to 2560
            self.assertNotIn(0x010F, img.getexif())
        with Image.open(photo.thumb.path) as img:
            self.assertLessEqual(max(img.size), 480)

        bad = SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg")
        self.assertEqual(self.client.post(reverse("display_photo_add"), {"photo": bad}).status_code, 400)

    def test_update_and_delete(self):
        self.client.post(reverse("display_photo_add"), {"photo": jpeg(), "seasons": "winter,spring,summer,fall"})
        photo = SaverPhoto.objects.get()
        self.assertEqual(photo.seasons, [])  # all four means any season
        url = reverse("display_photo_update", args=[photo.id])
        body = self.client.post(url, {"seasons": "fall,winter", "enabled": "0"}).json()
        self.assertEqual(body["seasons"], ["fall", "winter"])
        self.assertFalse(body["enabled"])
        path = photo.image.path
        self.client.post(reverse("display_photo_delete", args=[photo.id]))
        self.assertFalse(SaverPhoto.objects.exists())
        self.assertFalse(os.path.exists(path))

    def test_staff_only(self):
        self.client.post(reverse("display_photo_add"), {"photo": jpeg()})
        photo = SaverPhoto.objects.get()
        self.client.force_login(self.guest)
        for url in (reverse("display_upload_link"), reverse("display_photo_add"),
                    reverse("display_photo_update", args=[photo.id]),
                    reverse("display_photo_delete", args=[photo.id])):
            self.assertEqual(self.client.post(url, {"enabled": "0"}).status_code, 302, url)
        self.assertEqual(self.client.get(reverse("display_photos")).status_code, 302)
        self.assertTrue(SaverPhoto.objects.get().enabled)

    def test_saver_api_photos(self):
        AppSetting.objects.create(app_id="display", key="source_summer", value="photos")
        AppSetting.objects.create(app_id="display", key="source_winter", value="photos")
        self.client.post(reverse("display_photo_add"), {"photo": jpeg(), "seasons": "summer"})
        summer = self.client.get(reverse("display_saver_api"), {"season": "summer"}).json()
        self.assertEqual(summer["sources"], ["photos"])
        self.assertEqual(summer["photos"], [{"url": SaverPhoto.objects.get().image.url, "caption": ""}])
        winter = self.client.get(reverse("display_saver_api"), {"season": "winter"}).json()
        self.assertEqual(winter["sources"], ["stock"])  # no winter photos: fall back to the scene
        SaverPhoto.objects.update(enabled=False)
        summer = self.client.get(reverse("display_saver_api"), {"season": "summer"}).json()
        self.assertEqual(summer["sources"], ["stock"])

    def test_caption_from_exif_date(self):
        AppSetting.objects.create(app_id="display", key="source_summer", value="photos")
        self.client.post(reverse("display_photo_add"), {"photo": jpeg(taken="2024:03:31 23:30:00")})
        self.client.post(reverse("display_photo_add"), {"photo": jpeg(name="q.jpg")})
        dated = SaverPhoto.objects.exclude(taken_at=None).get()
        self.assertEqual((dated.taken_at.year, dated.taken_at.month, dated.taken_at.day), (2024, 3, 31))
        api = reverse("display_saver_api")
        off = self.client.get(api, {"season": "summer"}).json()["photos"]
        self.assertEqual({p["caption"] for p in off}, {""})
        AppSetting.objects.create(app_id="display", key="photo_caption", value=True)
        store.clear()
        on = self.client.get(api, {"season": "summer"}).json()["photos"]
        self.assertEqual(sorted(p["caption"] for p in on), ["", "March 2024"])

    def test_preview_overrides_are_staff_only(self):
        self.client.post(reverse("display_photo_add"), {"photo": jpeg(taken="2023:12:25 08:00:00")})
        api = reverse("display_saver_api")
        preview = {"season": "summer", "source": "photos", "rotate": "99", "caption": "1"}
        body = self.client.get(api, preview).json()
        self.assertEqual(body["sources"], ["photos"])
        self.assertEqual(body["rotate_seconds"], 60 * 60)  # clamped to the slider's range
        self.assertEqual(body["photos"][0]["caption"], "December 2023")
        self.client.force_login(self.guest)
        body = self.client.get(api, preview).json()
        self.assertEqual(body["sources"], ["stock"])
        self.assertEqual(body["photos"], [])
