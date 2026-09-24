"""Parse a Nuke .nk script (plain text) into a lightweight graph JSON.

No Nuke required. Handles: node blocks, push/set stack connections,
Group/end_group (collapsed), BackdropNode, tile_color.

Usage: python nk_parser.py "path/to/script.nk" [out_dir]
"""
import json
import re
import sys
from pathlib import Path

NODE_HEADER = re.compile(r"^\s*([A-Z][\w.]*)\s*\{")
SET_RE = re.compile(r"^\s*set\s+(\S+)\s+\[stack\s+(\d+)\]")
PUSH_RE = re.compile(r"^\s*push\s+(\S+)")
KNOB_RE = re.compile(r"^\s*(\S+)\s+(.*\S)\s*$")

KNOB_BLACKLIST = {
    "knobChanged", "onCreate", "onDestroy", "updateUI", "autolabel",
    "addUserKnob", "beforeRender", "afterRender", "beforeFrameRender",
    "afterFrameRender", "onScriptLoad", "onScriptSave",
}
# knobs that drive layout/identity, not shown in the properties panel
INTERNAL_KNOBS = {"name", "xpos", "ypos", "selected", "hide_input"}
ROOT_KNOBS = {"name", "first_frame", "last_frame", "fps", "format",
              "project_directory", "colorManagement", "frame"}


def brace_delta(line, in_quote):
    """Count { } outside double-quoted strings; returns (delta, in_quote)."""
    delta = 0
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            in_quote = not in_quote
        elif not in_quote:
            if c == "{":
                delta += 1
            elif c == "}":
                delta -= 1
        i += 1
    return delta, in_quote


def tile_color_to_hex(v):
    try:
        n = int(v, 16) if isinstance(v, str) and v.startswith("0x") else int(v)
    except (ValueError, TypeError):
        return None
    r = (n >> 24) & 0xFF
    g = (n >> 16) & 0xFF
    b = (n >> 8) & 0xFF
    if r == g == b == 0:
        return None
    return f"#{r:02x}{g:02x}{b:02x}"


def unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        v = v[1:-1]
    return v.replace('\\"', '"')


class Parser:
    def __init__(self, lines):
        self.lines = lines
        self.i = 0
        self.uid = 0
        self.nodes = []      # rendered (top-level) nodes
        self.edges = []      # [from_id, to_id, kind?]
        self.backdrops = []
        self.root = {}
        self.total_parsed = 0

    def parse(self):
        stack = []           # top-level connection stack
        named = {}
        group_depth = 0      # >0 means we're inside a Group body (collapsed)
        group_stack_frames = []  # saved (stack, named) per group level
        current_group = None
        group_children = 0

        while self.i < len(self.lines):
            line = self.lines[self.i]
            self.i += 1
            stripped = line.strip()
            if not stripped:
                continue

            m = SET_RE.match(line)
            if m:
                name, k = m.group(1), int(m.group(2))
                if len(stack) > k:
                    named[name] = stack[-1 - k]
                else:
                    named[name] = None
                continue

            m = PUSH_RE.match(line)
            if m:
                ref = m.group(1)
                if ref == "0":
                    stack.append(None)
                elif ref.startswith("$"):
                    stack.append(named.get(ref[1:]))
                else:
                    stack.append(None)
                continue

            if stripped == "end_group":
                if group_stack_frames:
                    stack, named = group_stack_frames.pop()
                    group_depth -= 1
                    if group_depth == 0 and current_group is not None:
                        current_group["children"] = group_children
                        current_group = None
                continue

            m = NODE_HEADER.match(line)
            if m:
                cls = m.group(1)
                knobs = self.read_block(line)
                self.total_parsed += 1

                if cls == "Root":
                    self.root = {k: unquote(v) for k, v in knobs.items()
                                 if k in ROOT_KNOBS}
                    continue

                if group_depth > 0:
                    group_children += 1
                    # children are collapsed; keep group-internal stack coherent
                    n_in = self.n_inputs(knobs, cls)
                    for _ in range(min(n_in, len(stack))):
                        stack.pop()
                    stack.append(None)
                    if cls == "Group":
                        group_stack_frames.append((stack, named))
                        stack, named = [], {}
                        group_depth += 1
                    continue

                node = self.make_node(cls, knobs)
                n_in = self.n_inputs(knobs, cls)
                # edge kind: 0 normal, 1 hidden input, 2 viewer connection
                kind = 2 if cls == "Viewer" else (
                    1 if knobs.get("hide_input") == "true" else 0)
                for k in range(min(n_in, len(stack))):
                    src = stack.pop()
                    if src is not None and node["type"] != "backdrop":
                        e = [src, node["id"]]
                        if kind:
                            e.append(kind)
                        self.edges.append(e)
                stack.append(node["id"] if node["type"] != "backdrop" else None)

                if node["type"] == "backdrop":
                    self.backdrops.append(node)
                else:
                    self.nodes.append(node)

                if cls == "Group":
                    group_stack_frames.append((stack, named))
                    stack, named = [], {}
                    group_depth = 1
                    current_group = node
                    group_children = 0
                continue

            # unknown directive that may open a block (clone, add_layer...)
            d, q = brace_delta(line, False)
            while d > 0 and self.i < len(self.lines):
                nd, q = brace_delta(self.lines[self.i], q)
                d += nd
                self.i += 1

        return self.result()

    def read_block(self, header_line):
        """Consume lines until the node block closes; return knobs."""
        knobs = {}
        depth, in_quote = brace_delta(header_line, False)
        while depth > 0 and self.i < len(self.lines):
            line = self.lines[self.i]
            self.i += 1
            if depth == 1 and not in_quote:
                km = KNOB_RE.match(line)
                if km:
                    k, v = km.group(1), km.group(2)
                    if k not in KNOB_BLACKLIST and k not in knobs:
                        if len(v) > 240:
                            v = v[:240] + " …"
                        elif v.count("{") > v.count("}"):
                            v += " …"   # multi-line value (curve etc.), truncated
                        knobs[k] = v
            d, in_quote = brace_delta(line, in_quote)
            depth += d
        return knobs

    @staticmethod
    def n_inputs(knobs, cls):
        if "inputs" in knobs:
            try:
                # "inputs 5+1" style (masks) -> take the sum
                return sum(int(p) for p in re.findall(r"\d+", knobs["inputs"]))
            except ValueError:
                return 1
        if cls in ("Read", "Constant", "CheckerBoard2", "BackdropNode", "StickyNote"):
            return 0
        return 1

    def make_node(self, cls, knobs):
        self.uid += 1
        node = {
            "id": self.uid,
            "class": cls,
            "name": unquote(knobs.get("name", cls)),
            "x": float(knobs.get("xpos", 0)),
            "y": float(knobs.get("ypos", 0)),
            "type": "backdrop" if cls == "BackdropNode" else "node",
        }
        color = tile_color_to_hex(knobs.get("tile_color"))
        if color:
            node["color"] = color
        label = unquote(knobs.get("label", ""))
        label = re.sub(r"<[^>]+>", "", label).strip()
        if label:
            node["label"] = label[:200]
        if cls == "BackdropNode":
            node["w"] = float(knobs.get("bdwidth", 200))
            node["h"] = float(knobs.get("bdheight", 200))
            node["fontSize"] = float(knobs.get("note_font_size", 20))
        if cls == "StickyNote":
            node["fontSize"] = float(knobs.get("note_font_size", 11))
        if cls == "Read" and "file" in knobs:
            node["file"] = unquote(knobs["file"])[-60:]
        panel = {k: v[:200] for k, v in knobs.items()
                 if k not in INTERNAL_KNOBS}
        if panel:
            node["knobs"] = dict(list(panel.items())[:48])
        return node

    def result(self):
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "backdrops": self.backdrops,
            "root": self.root,
            "stats": {
                "nodes": len(self.nodes),
                "edges": len(self.edges),
                "backdrops": len(self.backdrops),
                "totalParsed": self.total_parsed,
            },
        }


def parse_file(path):
    src = Path(path)
    text = src.read_text(encoding="utf-8", errors="replace")
    graph = Parser(text.splitlines()).parse()
    graph["source"] = src.name
    return graph


def main():
    src = Path(sys.argv[1])
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else src.parent
    graph = parse_file(src)

    (out_dir / "graph.json").write_text(
        json.dumps(graph, ensure_ascii=False), encoding="utf-8")
    (out_dir / "graph.js").write_text(
        "window.GRAPH = " + json.dumps(graph, ensure_ascii=False) + ";",
        encoding="utf-8")
    s = graph["stats"]
    print(f"{src.name}: {s['nodes']} nodes, {s['edges']} edges, "
          f"{s['backdrops']} backdrops (parsed {s['totalParsed']} blocks)")


if __name__ == "__main__":
    main()
