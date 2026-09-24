# -*- coding: utf-8 -*-
"""Supervisor annotation -> BackdropNode bridge.

When a script opens, looks for "<script>.nk.annotations.json" (written by the
nuke-web-preview viewer's autosave) and creates yellow SUP_ backdrops for each
note. Safe to re-open: existing SUP_ backdrops are synced, not duplicated.

Install: this folder is added via nuke.pluginAddPath in menu.py, then
`import annotation_backdrops`.
"""
import json
import os

import nuke

TILE_COLOR = 0xF1C40FFF
PREFIX = "SUP_note"


def _sidecar_path():
    script = nuke.root().name()
    if not script or script == "Root":
        return None
    return script + ".annotations.json"


def _load_notes():
    path = _sidecar_path()
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as f:
            doc = json.loads(f.read().decode("utf-8"))
        return doc.get("state", [])
    except Exception as e:  # never break script loading
        nuke.tprint("annotation_backdrops: failed to read %s (%s)" % (path, e))
        return None


def apply_sup_notes():
    notes = _load_notes()
    if notes is None:
        return
    existing = {n.name(): n for n in nuke.allNodes("BackdropNode")
                if n.name().startswith(PREFIX)}
    wanted = set()
    for i, a in enumerate(notes, 1):
        name = "%s%d" % (PREFIX, i)
        wanted.add(name)
        label = "SUP: %s" % a.get("text", "")
        b = existing.get(name)
        if b is None:
            b = nuke.nodes.BackdropNode(name=name)
        b["xpos"].setValue(int(a["x"]))
        b["ypos"].setValue(int(a["y"]))
        b["bdwidth"].setValue(int(a["w"]))
        b["bdheight"].setValue(int(a["h"]))
        b["tile_color"].setValue(TILE_COLOR)
        b["note_font_size"].setValue(30)
        b["z_order"].setValue(10)
        b["label"].setValue(label)
    # notes deleted in the viewer disappear here too
    for name, b in existing.items():
        if name not in wanted:
            nuke.delete(b)
    if notes:
        nuke.tprint("annotation_backdrops: %d supervisor note(s) applied"
                    % len(notes))


nuke.addOnScriptLoad(apply_sup_notes)
