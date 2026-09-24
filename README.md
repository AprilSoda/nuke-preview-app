# Nuke Preview App

Preview the node structure of a Nuke `.nk` script in the browser — no Nuke license needed — and leave supervisor notes that show up as backdrops when the artist opens the script.

A `.nk` file is plain text, so it is parsed directly. Parsing a 1.4 MB production comp takes about 0.3 s.

## Features

- **Fast graph viewer** — dependency-free Canvas renderer, Nuke-style navigation (wheel zoom, LMB/MMB/Alt pan, `F` to fit).
- **Properties panel** — click a node to see the knobs that differ from defaults.
- **Label evaluation** — a small TCL evaluator resolves DAG labels such as `[value root.name]`, `file tail/rootname`, `split/join/lrange/lindex`. Anything it can't evaluate is shown as raw text instead of guessed.
- **File browser and versions** — browse folders, recent files, `name_v###.nk` sibling list, and a version diff (added / removed nodes).
- **Supervisor annotations** — draw a box, type a note. Autosaved to `<script>.nk.annotations.json` next to the script (the original `.nk` is never modified), with full undo/redo history (`Ctrl+Z` / `Ctrl+Shift+Z`) that survives closing the browser.
- **Notes reach the artist as backdrops** — a Nuke hook creates yellow `SUP_note*` backdrops from the sidecar file on script load.

Group / Gizmo contents are collapsed into a single node with an inner-node count badge.

## Run

Requires Python 3.9+ (standard library only).

```bash
python server.py 8791
```

Open http://localhost:8791 and pick a file in the sidebar, or open `http://localhost:8791/?path=<absolute path to .nk>`.

Extra browse roots (separated by `;` on Windows, `:` elsewhere):

```bash
NUKE_PREVIEW_ROOTS="D:/projects;E:/shots" python server.py
```

Parse a single file to JSON:

```bash
python nk_parser.py "path/to/script.nk" out_dir
```

## Nuke hook

Add to your `menu.py` (adjust the path):

```python
nuke.pluginAddPath(r"C:\path\to\nuke-web-preview\nuke_hook")
import annotation_backdrops
```

On script load, notes from `<script>.nk.annotations.json` are synced to `SUP_note*` backdrops (existing ones are updated, deleted notes are removed).

## Layout

| File | Purpose |
| --- | --- |
| `nk_parser.py` | `.nk` text → graph JSON (nodes, edges, backdrops, knobs) |
| `server.py` | Local API: browse, graph (mtime-cached), versions, annotations |
| `viewer.html` | Single-file viewer and annotation UI |
| `nuke_hook/annotation_backdrops.py` | Sidecar notes → BackdropNodes inside Nuke |

## Known limits

- Edges are reconstructed from the `push`/`set` stack; unusual scripts may produce a few wrong edges.
- Values that need real render data (e.g. `[metadata ...]`) can't be evaluated.
- The server has no authentication and binds to `127.0.0.1` only. Don't expose it on a shared network as-is.
