"""Tests for decoding map layers (synthetic data)."""

from __future__ import annotations

import base64
import gzip
import unittest

from _loader import load
import fixtures

mapdata = load("mapdata")
robot = load("robot")


def pack(text: str) -> str:
    return base64.b64encode(gzip.compress(text.encode())).decode()


class GridTests(unittest.TestCase):
    """me2: one character per cell, bit flags for the cell type."""

    def test_me2_runs(self) -> None:
        # 3 x 2 grid: row 0 floor floor wall, row 1 empty obstacle floor
        cells = chr(4) + chr(4) + chr(2) + chr(0) + chr(8) + chr(4)
        grid = mapdata.decode_grid(
            {
                "x": 10,
                "y": 20,
                "w": 3,
                "h": 2,
                "mapData": pack(cells),
                "extra": {"mapEncodeType": "me2/gzip/base64"},
            }
        )
        self.assertEqual(grid.runs["floor"], [(10, 20, 2), (12, 21, 1)])
        self.assertEqual(grid.runs["wall"], [(12, 20, 1)])
        self.assertEqual(grid.runs["obstacle"], [(11, 21, 1)])

    def test_legacy_rle(self) -> None:
        # 'S' = 18 = 0b010010 -> floor, floor; '(5)' repeats it
        grid = mapdata.decode_grid({"x": 0, "y": 0, "w": 10, "h": 1, "mapData": "S(5)"})
        self.assertEqual(grid.runs["floor"], [(0, 0, 10)])

    def test_bad_layer(self) -> None:
        self.assertIsNone(mapdata.decode_grid({"x": 0}))


class OutlineTests(unittest.TestCase):
    """Room outlines and paths are delta encoded when compressed."""

    def test_compressed_room_is_delta_encoded(self) -> None:
        rooms = mapdata.decode_rooms(
            {"room": [{"roomID": 8, "coordinate": pack("10,10;5,0;0,5;-5,0")}]}
        )
        self.assertEqual(rooms[8], [(10, 10), (15, 10), (15, 15), (10, 15)])

    def test_plain_room_is_absolute(self) -> None:
        rooms = mapdata.decode_rooms(
            {"room": [{"roomID": 9, "coordinate": "1,1;4,1;4,4"}]}
        )
        self.assertEqual(rooms[9], [(1, 1), (4, 1), (4, 4)])

    def test_path_segments_continue_deltas(self) -> None:
        path = mapdata.decode_path({"pathdata": pack("0,0;1,0|0,2;1,0")})
        self.assertEqual(path, [[(0, 0), (1, 0)], [(1, 2), (2, 2)]])

    def test_empty_path(self) -> None:
        self.assertEqual(mapdata.decode_path({"pathdata": ""}), [])

    def test_build_layers(self) -> None:
        layers = mapdata.build_layers(
            {
                "x": 0,
                "y": 0,
                "w": 1,
                "h": 1,
                "mapData": pack(chr(4)),
                "chargerX": 5,
                "chargerY": 6,
                "extra": {"chargerDegree": 179},
            },
            None,
            {"pathdata": "", "currentPosition": {"x": 5, "y": 6, "degree": -174}},
        )
        self.assertEqual(layers.charger, (5.0, 6.0))
        self.assertEqual(layers.charger_degree, 179.0)
        self.assertEqual(layers.robot, (5.0, 6.0))
        self.assertEqual(layers.robot_degree, -174.0)


class PathScaleTests(unittest.TestCase):
    """The path is scaled only when it uses the finer coordinates."""

    grid = mapdata.Grid(880, 1054, 278, 191)

    def test_grid_coordinates_are_kept(self) -> None:
        # RS20: path points already lie on the map.
        path = [[(900.0, 1100.0), (1000.0, 1150.0)]]
        self.assertEqual(mapdata.fit_path(path, self.grid), path)

    def test_fine_coordinates_are_scaled(self) -> None:
        # RE4: the same points stored ten times larger.
        path = [[(9000.0, 11000.0), (10000.0, 11500.0)]]
        self.assertEqual(
            mapdata.fit_path(path, self.grid), [[(900.0, 1100.0), (1000.0, 1150.0)]]
        )

    def test_without_grid_nothing_changes(self) -> None:
        path = [[(9000.0, 11000.0)]]
        self.assertEqual(mapdata.fit_path(path, None), path)

    def test_room_names_from_region_layer(self) -> None:
        names = mapdata.decode_room_names(
            {"room": [{"roomID": 8, "roomName": " #@WoS# "}, {"roomID": 9}]}
        )
        self.assertEqual(names, {8: "#@WoS#"})


class RenderTests(unittest.TestCase):
    """The SVG contains every layer."""

    def test_render(self) -> None:
        maprender = load("maprender")
        cells = chr(4) * 30 + chr(2) * 10
        layers = mapdata.build_layers(
            {
                "x": 0,
                "y": 0,
                "w": 10,
                "h": 4,
                "mapData": pack(cells),
                "chargerX": 9,
                "chargerY": 1,
            },
            {"room": [{"roomID": 8, "coordinate": "0,0;9,0;9,2;0,2"}]},
            {"pathdata": "1,1;5,1", "currentPosition": {"x": 5, "y": 1, "degree": 90}},
        )
        svg = maprender.render_svg(layers, {8: "Bed & Room"}).decode()
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("<polygon", svg)
        self.assertIn("<polyline", svg)
        self.assertIn("Bed &amp; Room", svg)
        self.assertIn("<circle", svg)
        hidden = maprender.render_svg(layers, {}, show_path=False).decode()
        self.assertNotIn("<polyline", hidden)

    def test_no_grid(self) -> None:
        maprender = load("maprender")
        self.assertIsNone(maprender.render_svg(mapdata.MapLayers()))


class VersionTests(unittest.TestCase):
    def test_map_versions_from_task(self) -> None:
        self.assertEqual(
            robot.map_versions(fixtures.task(), 2),
            {"map": 6126, "region": 1359, "path": 204225},
        )
        self.assertEqual(robot.map_versions(fixtures.task(), 3), {})


if __name__ == "__main__":
    unittest.main()
