import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import hypr_displays_core as core  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "monitors.json")


def fixture():
    with open(FIXTURE) as fh:
        return json.load(fh)


def mon(name, x, y, w=1920, h=1080, scale=1.0, transform=0, enabled=True):
    """A monitor built from hyprctl-like data."""
    return core.Monitor({
        "name": name, "make": "Make", "model": name, "width": w, "height": h, "refreshRate": 60.0,
        "x": x, "y": y, "scale": scale, "transform": transform, "disabled": not enabled,
        "availableModes": [f"{w}x{h}@60.00Hz"],
    })


class ParsingTest(unittest.TestCase):
    def test_parse_mode(self):
        self.assertEqual(core.parse_mode("2560x1600@240.00Hz"), (2560, 1600, 240.0))
        self.assertEqual(core.parse_mode("1920x1080@59.94Hz"), (1920, 1080, 59.94))
        self.assertIsNone(core.parse_mode("garbage"))

    def test_fmt_num_drops_trailing_zeros(self):
        self.assertEqual(core.fmt_num(1.0), "1")
        self.assertEqual(core.fmt_num(1.25), "1.25")
        self.assertEqual(core.fmt_num(60.00), "60")
        self.assertEqual(core.fmt_num(59.94), "59.94")

    def test_mode_label(self):
        self.assertEqual(core.mode_label((1920, 1080, 59.94)), "1920x1080 @ 59.94 Hz")


class MonitorTest(unittest.TestCase):
    def setUp(self):
        self.edp, self.hdmi = (core.Monitor(d) for d in fixture())

    def test_reads_current_mode_and_position(self):
        self.assertEqual(self.edp.mode, (2560, 1600, 240.0))
        self.assertEqual((self.hdmi.x, self.hdmi.y), (2048, 100))
        self.assertTrue(self.edp.enabled)

    def test_desc_hides_serial_number(self):
        self.assertEqual(self.hdmi.desc, "Dell Inc. DELL P2319H")
        self.assertNotIn("SERIAL", self.hdmi.desc)

    def test_logical_size_uses_scale(self):
        self.assertEqual(self.edp.size(), (2048, 1280))

    def test_rotation_swaps_width_and_height(self):
        self.hdmi.transform = 1
        self.assertEqual(self.hdmi.size(), (1080, 1920))

    def test_disabled_monitor_without_size_uses_first_mode(self):
        data = fixture()[1]
        data.update(width=0, height=0, disabled=True)
        m = core.Monitor(data)
        self.assertFalse(m.enabled)
        self.assertEqual(m.mode, (1920, 1080, 60.0))

    def test_unknown_current_mode_is_added_to_list(self):
        data = fixture()[1]
        data.update(width=1280, height=720, refreshRate=75.0)
        m = core.Monitor(data)
        self.assertEqual(m.mode, (1280, 720, 75.0))
        self.assertIn((1280, 720, 75.0), m.modes)

    def test_lua(self):
        self.assertEqual(self.hdmi.lua(),
                         'hl.monitor({ output = "HDMI-A-1", mode = "1920x1080@60", position = "2048x100", scale = 1 })')
        self.edp.transform = 3
        self.assertIn("transform = 3", self.edp.lua())
        self.edp.enabled = False
        self.assertEqual(self.edp.lua(), 'hl.monitor({ output = "eDP-2", disabled = true })')


class GeometryTest(unittest.TestCase):
    def test_overlap(self):
        self.assertTrue(core.overlaps(mon("A", 0, 0), mon("B", 1000, 500)))
        self.assertFalse(core.overlaps(mon("A", 0, 0), mon("B", 1920, 0)))

    def test_touching_side_by_side_and_stacked(self):
        self.assertTrue(core.touches(mon("A", 0, 0), mon("B", 1920, 300)))
        self.assertTrue(core.touches(mon("A", 0, 0), mon("B", 500, 1080)))

    def test_gap_does_not_touch(self):
        self.assertFalse(core.touches(mon("A", 0, 0), mon("B", 1950, 0)))

    def test_corner_only_does_not_touch(self):
        # The mouse can't cross a single corner point.
        self.assertFalse(core.touches(mon("A", 0, 0), mon("B", 1920, 1080)))

    def test_problems(self):
        self.assertEqual(core.layout_problems([mon("A", 0, 0), mon("B", 1920, 0)]), ([], []))
        errors, _ = core.layout_problems([mon("A", 0, 0), mon("B", 100, 100)])
        self.assertEqual(errors, ["A overlaps B"])
        _, warnings = core.layout_problems([mon("A", 0, 0), mon("B", 3000, 0)])
        self.assertEqual(len(warnings), 2)

    def test_problems_ignore_disabled_monitors(self):
        self.assertEqual(core.layout_problems([mon("A", 0, 0), mon("B", 10, 10, enabled=False)]), ([], []))

    def test_normalize_moves_layout_to_origin(self):
        a, b = mon("A", -500, 200), mon("B", 1420, 300)
        core.normalize([a, b])
        self.assertEqual([(a.x, a.y), (b.x, b.y)], [(0, 0), (1920, 100)])


class SnapTest(unittest.TestCase):
    def setUp(self):
        self.fixed = mon("A", 0, 0)
        self.moving = mon("B", 0, 0)

    def test_snaps_to_right_edge(self):
        self.assertEqual(core.snap(self.moving, 1930, 5, [self.fixed], 20), (1920, 0))

    def test_snaps_below_and_centered(self):
        small = mon("C", 0, 0, w=1280, h=720)
        self.assertEqual(core.snap(small, 315, 1070, [self.fixed], 20), (320, 1080))

    def test_far_away_does_not_snap(self):
        self.assertEqual(core.snap(self.moving, 2500.4, 600.6, [self.fixed], 20), (2500, 601))

    def test_ignores_itself(self):
        self.assertEqual(core.snap(self.moving, 7, 7, [self.moving], 20), (7, 7))


class WorkspacesTest(unittest.TestCase):
    def setUp(self):
        self.mons = [core.Monitor(d) for d in fixture()]

    def test_initial_map_prefers_rules_then_open_workspaces_then_first_monitor(self):
        rules = [{"workspaceString": "1", "monitor": "eDP-2"}, {"workspaceString": "2", "monitor": "HDMI-A-1"},
                 {"workspaceString": "name:web", "monitor": "HDMI-A-1"}, {"workspaceString": "3", "monitor": "DP-9"}]
        open_ws = [{"id": 4, "monitor": "HDMI-A-1"}, {"id": 2, "monitor": "eDP-2"}]
        ws = core.initial_ws_map(self.mons, rules, open_ws)
        self.assertEqual(ws[1], "eDP-2")
        self.assertEqual(ws[2], "HDMI-A-1")  # rule wins over where it is open now
        self.assertEqual(ws[3], "eDP-2")     # rule for an unknown monitor is ignored
        self.assertEqual(ws[4], "HDMI-A-1")
        self.assertEqual(sorted(ws), list(range(1, 11)))

    def test_lua_lines_mark_first_workspace_of_each_monitor_as_default(self):
        ws = {n: ("eDP-2" if n % 2 else "HDMI-A-1") for n in range(1, 11)}
        lines = core.lua_lines(self.mons, ws)
        self.assertEqual(lines[0], self.mons[0].lua())
        self.assertIn('hl.workspace_rule({ workspace = "1", monitor = "eDP-2", default = true })', lines)
        self.assertIn('hl.workspace_rule({ workspace = "2", monitor = "HDMI-A-1", default = true })', lines)
        self.assertIn('hl.workspace_rule({ workspace = "3", monitor = "eDP-2", default = false })', lines)
        self.assertEqual(len(lines), 12)

    def test_workspace_moves_only_for_open_workspaces_on_wrong_monitor(self):
        ws = {n: "eDP-2" for n in range(1, 11)}
        ws[2] = "HDMI-A-1"
        open_ws = [{"id": 1, "monitor": "eDP-2"}, {"id": 2, "monitor": "eDP-2"}, {"id": 4, "monitor": "HDMI-A-1"}]
        self.assertEqual(core.workspace_moves(open_ws, ws), [
            'hl.dispatch(hl.dsp.workspace.move({ workspace = "2", monitor = "HDMI-A-1" }))',
            'hl.dispatch(hl.dsp.workspace.move({ workspace = "4", monitor = "eDP-2" }))',
        ])


class ConfigBlockTest(unittest.TestCase):
    BLOCK = core.make_block(['hl.monitor({ output = "A", disabled = true })'])

    def test_block_has_markers(self):
        self.assertTrue(self.BLOCK.startswith(core.BEGIN))
        self.assertTrue(self.BLOCK.endswith(core.END))

    def test_replaces_existing_block_and_keeps_the_rest(self):
        text = f"-- top\n{core.BEGIN}\nold line\n{core.END}\n-- bottom\n"
        out = core.replace_block(text, self.BLOCK)
        self.assertEqual(out, f"-- top\n{self.BLOCK}\n-- bottom\n")

    def test_appends_block_when_missing(self):
        self.assertEqual(core.replace_block("-- user stuff\n\n", self.BLOCK), f"-- user stuff\n\n{self.BLOCK}\n")

    def test_empty_file(self):
        self.assertEqual(core.replace_block("", self.BLOCK), f"{self.BLOCK}\n")

    def test_begin_without_end_is_an_error(self):
        # Never guess: a broken block could eat the user's config below it.
        with self.assertRaises(ValueError):
            core.replace_block(f"{core.BEGIN}\nhalf a block\n-- user stuff\n", self.BLOCK)

    def test_save_is_idempotent(self):
        once = core.replace_block("-- x\n", self.BLOCK)
        self.assertEqual(core.replace_block(once, self.BLOCK), once)


if __name__ == "__main__":
    unittest.main()
