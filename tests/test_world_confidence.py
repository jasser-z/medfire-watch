import json

from medfire_watch.world_hotspots import load_world_hotspots


def test_viirs_low_confidence_shorthand_is_excluded_from_legacy_cache(tmp_path):
    path = tmp_path / 'world.json'
    path.write_text(json.dumps({'observations': 4, 'detections': [
        {'confidence': 'l'}, {'confidence': 'low'}, {'confidence': 'n'}, {'confidence': 'h'},
    ]}), encoding='utf-8')
    world = load_world_hotspots(path)
    assert world['observations'] == 2
    assert [d['confidence'] for d in world['detections']] == ['n', 'h']


def test_background_refresh_runs_without_browser_and_stops(monkeypatch):
    import api.main as api
    calls = []
    monkeypatch.setattr(api, '_refresh_map_data', lambda: calls.append('refresh'))

    class Stop:
        def is_set(self):
            return False

        def wait(self, seconds):
            assert seconds == 60
            return len(calls) == 2

    api._world_refresh_loop(Stop())
    assert calls == ['refresh', 'refresh']
