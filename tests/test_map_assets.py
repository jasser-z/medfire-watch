import re

from api.main import app
from fastapi.testclient import TestClient
from medfire_watch import map_assets


def test_embedded_map_versions_the_entire_module_chain(monkeypatch):
    monkeypatch.setattr('api.main._refresh_map_data', lambda: None)
    client = TestClient(app)
    html = client.get('/world-map?v=obsolete')
    script = re.search(r'src="(/world-map/app.mjs\?v=[a-f0-9]+)"', html.text).group(1)
    module = client.get(script)
    assert 'no-store' in html.headers['cache-control']
    assert 'no-store' in module.headers['cache-control']
    weather = re.search(r"from '(/fire-weather/module.mjs\?v=[a-f0-9]+)'", module.text).group(1)
    response = client.get(weather)
    assert 'no-store' in response.headers['cache-control']
    assert "createElement('select')" not in response.text
    assert 'currentDate' in response.text


def test_weather_change_invalidates_parent_iframe_version(tmp_path, monkeypatch):
    folder = tmp_path / 'dashboard'
    folder.mkdir()
    for name in map_assets.ASSETS:
        (folder / name).write_text('initial', encoding='utf-8')
    monkeypatch.setattr(map_assets, 'PROJECT_ROOT', tmp_path)
    before = map_assets.map_asset_version()
    (folder / 'fire_weather_layer.mjs').write_text('updated', encoding='utf-8')
    assert before != map_assets.map_asset_version()
