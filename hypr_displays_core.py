"""Layout logic for hypr-displays: no GTK, no hyprctl calls, so it can be unit tested."""

import re

BEGIN = "-- BEGIN hypr-displays"
END = "-- END hypr-displays"
WORKSPACES = range(1, 11)
EPS = 0.5  # logical pixels; positions are rounded, sizes can be fractional with odd scales


def fmt_num(v):
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s or "0"


def mode_label(mode):
    w, h, r = mode
    return f"{w}x{h} @ {fmt_num(round(r, 2))} Hz"


def parse_mode(s):
    m = re.match(r"(\d+)x(\d+)@([\d.]+)Hz", s)
    return (int(m[1]), int(m[2]), float(m[3])) if m else None


class Monitor:
    """One output, built from an entry of `hyprctl monitors all -j`."""

    def __init__(self, data):
        self.name = data["name"]
        # make + model only: "description" also carries the serial number
        self.desc = f'{data.get("make", "")} {data.get("model", "")}'.strip() or data.get("description", "")
        self.modes = [m for m in (parse_mode(s) for s in data.get("availableModes", [])) if m]
        current = (data["width"], data["height"], round(data["refreshRate"], 2))
        if data["width"] and data["height"]:
            match = next((m for m in self.modes if m[0] == current[0] and m[1] == current[1]
                          and abs(m[2] - current[2]) < 0.05), None)
            if not match:
                match = current
                self.modes.insert(0, current)
        else:
            match = self.modes[0] if self.modes else (1920, 1080, 60.0)
        self.mode = match
        self.x, self.y = data["x"], data["y"]
        self.scale = data["scale"] or 1.0
        self.transform = data.get("transform", 0) % 4
        self.enabled = not data.get("disabled", False)

    def size(self):
        w, h = self.mode[0] / self.scale, self.mode[1] / self.scale
        return (h, w) if self.transform % 2 else (w, h)

    def rect(self):
        w, h = self.size()
        return self.x, self.y, w, h

    def lua(self):
        if not self.enabled:
            return f'hl.monitor({{ output = "{self.name}", disabled = true }})'
        w, h, r = self.mode
        parts = [f'output = "{self.name}"', f'mode = "{w}x{h}@{fmt_num(round(r, 2))}"',
                 f'position = "{int(self.x)}x{int(self.y)}"', f"scale = {fmt_num(self.scale)}"]
        if self.transform:
            parts.append(f"transform = {self.transform}")
        return "hl.monitor({ " + ", ".join(parts) + " })"


def _spans(a, b):
    """Overlap length of the two rects on the x axis and on the y axis (negative = gap)."""
    ax, ay, aw, ah = a.rect()
    bx, by, bw, bh = b.rect()
    return min(ax + aw, bx + bw) - max(ax, bx), min(ay + ah, by + bh) - max(ay, by)


def overlaps(a, b):
    sx, sy = _spans(a, b)
    return sx > EPS and sy > EPS


def touches(a, b):
    """True when the two screens share a piece of edge, so the mouse can cross."""
    sx, sy = _spans(a, b)
    return (abs(sx) <= EPS and sy > EPS) or (abs(sy) <= EPS and sx > EPS)


def layout_problems(monitors):
    """(errors, warnings) for the enabled monitors. Errors block Apply/Save."""
    mons = [m for m in monitors if m.enabled]
    errors, warnings = [], []
    for i, a in enumerate(mons):
        for b in mons[i + 1:]:
            if overlaps(a, b):
                errors.append(f"{a.name} overlaps {b.name}")
    if len(mons) > 1:
        for a in mons:
            if not any(touches(a, b) for b in mons if b is not a):
                warnings.append(f"{a.name} does not touch any other display (mouse can't cross)")
    return errors, warnings


def normalize(monitors):
    """Shift the enabled monitors so the layout starts at 0,0."""
    mons = [m for m in monitors if m.enabled]
    if not mons:
        return
    mx, my = min(m.x for m in mons), min(m.y for m in mons)
    for m in mons:
        m.x, m.y = round(m.x - mx), round(m.y - my)


def snap(m, nx, ny, others, threshold):
    """Position for `m` dragged to (nx, ny), snapped to the closest edge of `others` within threshold."""
    w, h = m.size()
    best_x, dist_x = None, threshold
    best_y, dist_y = None, threshold
    for o in others:
        if o is m or not o.enabled:
            continue
        ox, oy, ow, oh = o.rect()
        for c in (ox + ow, ox - w, ox, ox + ow - w, ox + (ow - w) / 2):
            if abs(c - nx) < dist_x:
                best_x, dist_x = c, abs(c - nx)
        for c in (oy + oh, oy - h, oy, oy + oh - h, oy + (oh - h) / 2):
            if abs(c - ny) < dist_y:
                best_y, dist_y = c, abs(c - ny)
    return round(nx if best_x is None else best_x), round(ny if best_y is None else best_y)


def initial_ws_map(monitors, rules, open_workspaces):
    """Workspace -> monitor: from workspace rules, then where it is open now, then the first enabled monitor."""
    names = [m.name for m in monitors]
    ws_map = {}
    for rule in rules:
        ws = rule.get("workspaceString", "")
        if ws.isdigit() and int(ws) in WORKSPACES and rule.get("monitor") in names:
            ws_map[int(ws)] = rule["monitor"]
    for ws in open_workspaces:
        if ws["id"] in WORKSPACES and ws["monitor"] in names:
            ws_map.setdefault(ws["id"], ws["monitor"])
    enabled = [m.name for m in monitors if m.enabled] or names
    for n in WORKSPACES:
        ws_map.setdefault(n, enabled[0])
    return ws_map


def lua_lines(monitors, ws_map):
    lines = [m.lua() for m in monitors]
    seen = set()
    for n in WORKSPACES:
        mon = ws_map[n]
        default = mon not in seen
        seen.add(mon)
        lines.append(f'hl.workspace_rule({{ workspace = "{n}", monitor = "{mon}", default = {str(default).lower()} }})')
    return lines


def workspace_moves(open_workspaces, ws_map):
    """Lua dispatches that move open workspaces to their assigned monitor."""
    current = {w["id"]: w["monitor"] for w in open_workspaces}
    return [f'hl.dispatch(hl.dsp.workspace.move({{ workspace = "{n}", monitor = "{ws_map[n]}" }}))'
            for n in WORKSPACES if n in current and current[n] != ws_map[n]]


def make_block(lines):
    return "\n".join([f"{BEGIN} (generated by hypr-displays; edits inside this block are overwritten)",
                      *lines, END])


def replace_block(text, block):
    """Put `block` in place of the managed block in `text`, or append it."""
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if pattern.search(text):
        return pattern.sub(lambda _m: block, text)
    if BEGIN in text:
        raise ValueError(f"Found '{BEGIN}' without '{END}'. Fix the config file by hand first.")
    if not text.strip():
        return block + "\n"
    return text.rstrip("\n") + "\n\n" + block + "\n"
