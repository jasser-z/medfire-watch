from html.parser import HTMLParser
from pathlib import Path


def test_camera_fullscreen_contains_video_and_overlay():
    class StageParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_stage = False
            self.children = set()

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if attrs.get('class') == 'stage':
                self.in_stage = True
            if self.in_stage and tag in {'video', 'canvas'}:
                self.children.add(tag)

    page = (Path(__file__).parents[1] / 'dashboard/live_camera.html').read_text(encoding='utf-8')
    parser = StageParser()
    parser.feed(page)
    assert parser.children == {'video', 'canvas'}
    assert 'cameraStage.requestFullscreen()' in page
    assert 'cameraStage.append(cameraHud)' in page
