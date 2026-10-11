"""Routing only: reachable event preference, frame reuse and model reuse."""
from unittest.mock import Mock

import pytest
from PIL import Image

from utils.runtime_paths import SOURCE_ROOT


@pytest.fixture
def route(monkeypatch):
    from module.config import cfg
    from tasks.mirror import search_road
    from utils.path_manager import path_manager

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "backend": "playcover", "game_profile": "ios_en", "set_win_size": 1080,
    }))
    path_manager.initialize_paths()
    monkeypatch.setattr(search_road, "sleep", lambda _: None)
    return search_road


def graph_with_branches(route, *, dead_event=False, events=False, hard=False):
    graph = route.RouteGraph([], route.Row.MID, (0, 0), hard_mode=True)
    start = graph.columns["column1"][route.Row.MID]
    event = route.Node("event", 1)
    other = route.Node("event" if events else "shop", 2)
    expensive = route.Node("risky_encounter", 7)
    cheap = route.Node("shop", 2)
    boss = route.Node("boss_battle", 6)
    graph.columns["column2"] = {route.Row.TOP: event, route.Row.MID: other}
    graph.columns["column3"] = {route.Row.TOP: expensive, route.Row.MID: cheap}
    graph.column_count = 3
    if not hard:
        graph.columns["column4"] = {route.Row.MID: boss}
        graph.column_count = 4
        expensive.add_next_node(boss)
        cheap.add_next_node(boss)
    start.add_next_node(other)
    start.add_next_node(event)
    if not dead_event:
        event.add_next_node(expensive)
    other.add_next_node(cheap)
    return graph


@pytest.mark.parametrize("hard", [False, True])
def test_reachable_event_precedes_cheaper_shop_route(route, hard):
    graph = graph_with_branches(route, hard=hard)
    weight, path = graph.find_min_weight_route()
    assert path[1].node_class == "event"
    assert weight == sum(node.weight for node in path)


def test_dead_end_event_does_not_precede_reachable_exit(route):
    graph = graph_with_branches(route, dead_event=True)
    _, path = graph.find_min_weight_route()
    assert path[1].node_class == "shop"
    assert path[-1].node_class == "boss_battle"


def test_event_ties_retain_original_total_weight(route):
    graph = graph_with_branches(route, events=True)
    weight, path = graph.find_min_weight_route()
    assert path[2].weight == 2
    assert weight == 11


def test_unconnected_map_returns_no_route(route):
    graph = graph_with_branches(route)
    graph.columns["column1"][route.Row.MID].next_nodes.clear()
    assert graph.find_min_weight_route() == (float("inf"), [])


def test_real_map_reuses_one_frame_and_clicks_detected_node(route, monkeypatch):
    image = Image.open(SOURCE_ROOT / "tests/fixtures/playcover/mirror_map_floor2.png").convert("RGB")

    def capture(gray=True, **kwargs):
        route.auto.screenshot = image.convert("L") if gray else image
        return route.auto.screenshot

    screenshot = Mock(side_effect=capture)
    monkeypatch.setattr(route.auto, "take_screenshot", screenshot)
    monkeypatch.setattr(route.auto, "model", "normal")
    drag, click, enter = Mock(), Mock(), Mock(return_value=True)
    monkeypatch.setattr(route.auto, "mouse_drag", drag)
    monkeypatch.setattr(route.auto, "mouse_click", click)
    monkeypatch.setattr(route.auto, "click_element", enter)
    route.auto.clear_img_cache()
    mirror = route.MirrorMap()
    direction = mirror.get_next_step()
    assert direction == "U"
    screenshot.assert_called_once_with(gray=False, max_age=0.85)
    drag.assert_not_called()
    assert mirror.enter_next_node(direction)
    x, y = click.call_args.args
    assert 1070 < x < 1100 and 90 < y < 130
    assert mirror._next_position == []


def test_missing_bus_moves_camera_once_only_on_map(route, monkeypatch):
    monkeypatch.setattr(route.auto, "take_screenshot", Mock(return_value=True))
    monkeypatch.setattr(route.auto, "screenshot", Image.new("RGB", (1920, 1080)))
    find = Mock(side_effect=[None, True, None])
    monkeypatch.setattr(route.auto, "find_element", find)
    drag = Mock()
    monkeypatch.setattr(route.auto, "mouse_drag", drag)
    assert route.search_road_from_road_map() == ([], [])
    drag.assert_called_once()
    assert route.auto.take_screenshot.call_count == 2
    find.side_effect = [None, None]
    drag.reset_mock()
    assert route.search_road_from_road_map() == ([], [])
    drag.assert_not_called()


def test_next_step_never_reuses_stale_route_or_click_coordinates(route, monkeypatch):
    mirror = route.MirrorMap()
    mirror.floor_map = ["D"]
    mirror._next_position = [500, 600]
    plan = Mock(return_value=([], []))
    monkeypatch.setattr(route, "search_road_from_road_map", plan)
    assert mirror.get_next_step() is False
    assert mirror._next_position == []
    plan.assert_called_once()


def test_model_session_is_loaded_once(route, monkeypatch):
    import onnxruntime

    route._node_detection_session.cache_clear()
    factory = Mock()
    monkeypatch.setattr(onnxruntime, "InferenceSession", factory)
    try:
        assert route._node_detection_session() is route._node_detection_session()
        factory.assert_called_once()
    finally:
        route._node_detection_session.cache_clear()


def test_fallback_event_weight_exceeds_shop(route, monkeypatch):
    monkeypatch.setattr(route.auto, "find_feature_element", Mock(side_effect=[True]))
    assert route.get_node_weight(500, 500) == 4
    monkeypatch.setattr(route.auto, "find_feature_element", Mock(side_effect=[False, True]))
    assert route.get_node_weight(500, 500) == 3
