import json
from pathlib import Path
import tempfile
import time
import unittest
from swarmops.console import ConsoleEngine, console_preset, validate_console_scenario


class ConsoleTests(unittest.TestCase):
    def test_persistence_replays_and_pauses(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = ConsoleEngine(tmp, threaded=False)
            for _ in range(25): first.command({"action": "step"})
            first.command({"action": "speed", "value": 14})
            before = first.export("trace")
            first.close()
            second = ConsoleEngine(tmp, threaded=False)
            try:
                after = second.export("trace")
                # Logical replay is deterministic; measured CPU time is not.
                for exported in (before, after):
                    for run in exported["runs"]:
                        run["summary"].pop("planner_seconds")
                self.assertEqual(after, before)
                self.assertEqual(second.speed, 14)
                self.assertFalse(second.playing)
                self.assertTrue(second.restored)
            finally: second.close()

    def test_commands_reset_policy_and_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = ConsoleEngine(tmp, threaded=False)
            try:
                engine.command({"action": "step"})
                state = engine.command({"action": "policy", "value": "congestion"})
                self.assertEqual(state["runs"][0]["summary"]["tick"], 0)
                self.assertEqual(state["runs"][0]["policy"], "congestion")
                for data in ({"action": "speed", "value": 500}, {"action": "preset", "preset": "../file", "seed": 0},
                             {"action": "preset", "preset": "light", "seed": -1}, {"action": "compare", "value": "true"}):
                    with self.assertRaises(ValueError): engine.command(data)
                self.assertEqual(engine.command({"action": "reset"})["runs"][0]["summary"]["tick"], 0)
                with self.assertRaises(ValueError): engine.export("../../anything")
            finally: engine.close()

    def test_import_validation_and_independent_snapshot(self):
        scenario = json.loads(console_preset("light", 3).to_json())
        self.assertTrue(validate_console_scenario(scenario))
        scenario["walls"].append(scenario["parking"][0])
        with self.assertRaises(ValueError): validate_console_scenario(scenario)
        with tempfile.TemporaryDirectory() as tmp:
            engine = ConsoleEngine(tmp, threaded=False)
            try:
                state = engine.snapshot()
                state["runs"][0]["robots"][0]["cell"] = (999, 999)
                self.assertNotEqual(engine.snapshot()["runs"][0]["robots"][0]["cell"], (999, 999))
            finally: engine.close()

    def test_background_experiment_and_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = ConsoleEngine(tmp, threaded=False)
            try:
                engine.start_experiment()
                engine.command({"action": "step"})
                engine.cancel_experiment()
                engine.task_thread.join(timeout=5)
                self.assertEqual(engine.snapshot()["task"]["status"], "cancelled")
                engine.command({"action": "scenario", "scenario": {
                    **json.loads(console_preset("light", 4).to_json()),
                    "orders": [], "horizon": 5, "closures": [], "pauses": []}})
                engine.start_experiment()
                engine.task_thread.join(timeout=5)
                self.assertEqual(engine.snapshot()["task"]["status"], "complete")
                self.assertEqual(len(engine.snapshot()["task"]["results"]), 3)
            finally: engine.close()


try:
    from fastapi.testclient import TestClient
    from swarmops.web import create_app
except ImportError:
    TestClient = None


@unittest.skipIf(TestClient is None, "Install requirements-web.txt for API checks")
class ApiTests(unittest.TestCase):
    def test_real_backend_commands_inference_and_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            with TestClient(create_app(tmp, threaded=False, test_host=True)) as client:
                self.assertEqual(client.get('/health').status_code, 200)
                self.assertEqual(client.post('/api/command', json={"action": "step"}).json()["runs"][0]["summary"]["tick"], 1)
                client.post('/api/command', json={"action": "policy", "value": "learned"})
                for _ in range(12): client.post('/api/command', json={"action": "step"})
                state = client.get('/api/state').json()
                self.assertEqual(state['runs'][0]['policy'], 'learned')
                self.assertGreater(len(state['runs'][0]['paths']), 0)
                self.assertEqual(client.get('/api/export/trace').json()['model_id'], state['model']['model_id'])
                self.assertEqual(client.get('/api/export/anything').status_code, 404)

    def test_security_and_invalid_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            with TestClient(create_app(tmp, threaded=False, test_host=True)) as client:
                self.assertEqual(client.post('/api/command', json={'action':'play'}, headers={'Origin':'https://example.com'}).status_code,403)
                self.assertEqual(client.get('/api/state', headers={'Host':'attacker.example'}).status_code,403)
                self.assertEqual(client.post('/api/command', content='{}', headers={'Content-Type':'text/plain'}).status_code,415)
                self.assertEqual(client.post('/api/command', json=[], headers={}).status_code,400)
                self.assertEqual(client.post('/api/command', json={'action':'speed','value':-8}).status_code,400)
                self.assertFalse(client.post('/api/validate', json={'scenario':{}}).json()['valid'])
                self.assertEqual(client.get('/api/state').json()['runs'][0]['summary']['tick'],0)
                self.assertEqual(client.get('/../pyproject.toml').status_code,404)


if __name__ == '__main__': unittest.main()
