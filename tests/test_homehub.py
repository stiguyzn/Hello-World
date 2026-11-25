import json
import threading
import unittest
import urllib.error
import urllib.request
from urllib.parse import quote

from homehub.config import Config
from homehub.hub import Hub
from homehub.main import build_providers, make_server
from homehub.providers.base import Device, Provider, ProviderError
from homehub.providers.demo import DemoProvider


class DemoProviderTests(unittest.TestCase):
    def setUp(self):
        self.p = DemoProvider(seed=1)

    def test_devices_have_provider_prefixed_ids(self):
        devs = self.p.devices()
        self.assertGreaterEqual(len(devs), 4)
        for d in devs:
            self.assertTrue(d.id.startswith("demo:"), d.id)
        kinds = {d.kind for d in devs}
        self.assertTrue({"camera", "doorbell", "light", "alarm"} <= kinds)

    def test_arm_and_light_actions_change_state(self):
        self.p.action("driveway", "disarm")
        self.p.action("porch_light", "light_on")
        by = {d.extra["native_id"]: d for d in self.p.devices()}
        self.assertFalse(by["driveway"].armed)
        self.assertTrue(by["porch_light"].on)

    def test_action_is_logged_as_event(self):
        self.p.action("home_system", "arm")
        self.assertEqual(self.p.events(1)[0].kind, "arm")

    def test_unsupported_action_rejected(self):
        with self.assertRaises(ProviderError):
            self.p.action("porch_light", "arm")
        with self.assertRaises(ProviderError):
            self.p.action("nope", "arm")

    def test_snapshot_is_jpeg(self):
        img = self.p.snapshot("front_door")
        self.assertTrue(img.startswith(b"\xff\xd8") and img.endswith(b"\xff\xd9"))
        self.assertIsNone(self.p.snapshot("porch_light"))


class BrokenProvider(Provider):
    name = "broken"

    def connect(self):
        raise ProviderError("bad password")

    def devices(self):
        raise ProviderError("not connected")


class CountingProvider(Provider):
    name = "count"

    def __init__(self):
        self.calls = 0
        self.snaps = 0

    def devices(self):
        self.calls += 1
        return [Device(id="count:1", name="X", kind="camera", provider="count", has_snapshot=True)]

    def snapshot(self, native_id):
        self.snaps += 1
        return b"img"

    def action(self, native_id, action):
        pass


class HubTests(unittest.TestCase):
    def test_failing_provider_does_not_hide_others(self):
        hub = Hub([DemoProvider(), BrokenProvider()])
        hub.connect_all()
        self.assertIn("broken", hub.errors)
        self.assertTrue(hub.devices())

    def test_device_list_is_cached_until_action(self):
        c = CountingProvider()
        hub = Hub([c], cache_seconds=60)
        hub.devices()
        hub.devices()
        self.assertEqual(c.calls, 1)
        hub.action("count:1", "arm")
        hub.devices()
        self.assertEqual(c.calls, 2)

    def test_snapshot_cached_until_new_snapshot_requested(self):
        c = CountingProvider()
        hub = Hub([c], snapshot_seconds=60)
        hub.snapshot("count:1")
        hub.snapshot("count:1")
        self.assertEqual(c.snaps, 1)
        hub.action("count:1", "snapshot")
        hub.snapshot("count:1")
        self.assertEqual(c.snaps, 2)

    def test_unknown_device(self):
        hub = Hub([DemoProvider()])
        with self.assertRaises(ProviderError):
            hub.action("ring:123", "arm")
        with self.assertRaises(ProviderError):
            hub.action("demo", "arm")


class ConfigTests(unittest.TestCase):
    def test_from_env(self):
        cfg = Config.from_env({"HOMEHUB_PROVIDERS": "Ring, blink", "HOMEHUB_PORT": "9000",
                               "HOMEHUB_PIN": "1234", "HOMEHUB_DATA_DIR": "/tmp/hh"})
        self.assertEqual(cfg.providers, ["ring", "blink"])
        self.assertEqual(cfg.port, 9000)
        self.assertEqual(cfg.pin, "1234")
        self.assertEqual(cfg.ring_token_file, "/tmp/hh/ring_token.json")

    def test_defaults_to_demo(self):
        self.assertEqual(Config.from_env({}).providers, ["demo"])

    def test_unknown_provider_rejected(self):
        with self.assertRaises(SystemExit):
            build_providers(Config(providers=["nest"]))


class ServerTests(unittest.TestCase):
    pin = None

    def setUp(self):
        cfg = Config(host="127.0.0.1", port=0, pin=self.pin)
        self.hub = Hub([DemoProvider()])
        self.srv = make_server(self.hub, cfg)
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, r.headers, r.read()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_serves_ui(self):
        for path, needle in [("/", b"camera-grid"), ("/static/app.css", b"--tap"),
                             ("/static/app.js", b"loadDevices")]:
            status, _, body = self.get(path)
            self.assertEqual(status, 200)
            self.assertIn(needle, body)

    def test_static_path_traversal_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/static/../main.py")
        self.assertEqual(cm.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError):
            self.get("/static/%2e%2e/main.py")

    def test_devices_and_events(self):
        _, _, body = self.get("/api/devices")
        data = json.loads(body)
        self.assertTrue(any(d["kind"] == "doorbell" for d in data["devices"]))
        _, _, body = self.get("/api/events?limit=2")
        self.assertEqual(len(json.loads(body)["events"]), 2)

    def test_action_round_trip(self):
        status, data = self.post("/api/devices/%s/action" % quote("demo:porch_light"), {"action": "light_on"})
        self.assertEqual((status, data), (200, {"ok": True}))
        devs = json.loads(self.get("/api/devices")[2])["devices"]
        light = [d for d in devs if d["id"] == "demo:porch_light"][0]
        self.assertTrue(light["on"])

    def test_bad_action(self):
        status, data = self.post("/api/devices/demo:porch_light/action", {"action": "explode"})
        self.assertEqual(status, 400)
        status, _ = self.post("/api/devices/demo:porch_light/action", {})
        self.assertEqual(status, 400)

    def test_snapshot(self):
        status, headers, body = self.get("/api/snapshot/" + quote("demo:driveway"))
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/jpeg")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/api/snapshot/demo:porch_light")
        self.assertEqual(cm.exception.code, 404)


class PinServerTests(ServerTests):
    pin = "2468"

    def test_arm_needs_pin(self):
        url = "/api/devices/demo:home_system/action"
        self.assertEqual(self.post(url, {"action": "arm"})[0], 403)
        self.assertEqual(self.post(url, {"action": "arm", "pin": "0000"})[0], 403)
        self.assertEqual(self.post(url, {"action": "arm", "pin": "2468"})[0], 200)
        status = json.loads(self.get("/api/status")[2])
        self.assertTrue(status["pin_required"])

    def test_light_needs_no_pin(self):
        self.assertEqual(self.post("/api/devices/demo:porch_light/action", {"action": "light_on"})[0], 200)


if __name__ == "__main__":
    unittest.main()
