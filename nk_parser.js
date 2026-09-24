/* Browser/Node port of nk_parser.py: .nk text -> lightweight graph object.
   Keep behaviour identical to the Python parser. */
(function (root) {
  'use strict';
  const NODE_HEADER = /^\s*([A-Z][\w.]*)\s*\{/;
  const SET_RE = /^\s*set\s+(\S+)\s+\[stack\s+(\d+)\]/;
  const PUSH_RE = /^\s*push\s+(\S+)/;
  const KNOB_RE = /^\s*(\S+)\s+(.*\S)\s*$/;
  const KNOB_BLACKLIST = new Set([
    'knobChanged', 'onCreate', 'onDestroy', 'updateUI', 'autolabel',
    'addUserKnob', 'beforeRender', 'afterRender', 'beforeFrameRender',
    'afterFrameRender', 'onScriptLoad', 'onScriptSave']);
  const INTERNAL_KNOBS = new Set(['name', 'xpos', 'ypos', 'selected', 'hide_input']);
  const ROOT_KNOBS = new Set(['name', 'first_frame', 'last_frame', 'fps', 'format',
    'project_directory', 'colorManagement', 'frame']);
  const ZERO_INPUT = new Set(['Read', 'Constant', 'CheckerBoard2', 'BackdropNode', 'StickyNote']);

  function braceDelta(line, inQuote) {
    let delta = 0;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (c === '\\') { i++; continue; }
      if (c === '"') inQuote = !inQuote;
      else if (!inQuote) {
        if (c === '{') delta++;
        else if (c === '}') delta--;
      }
    }
    return [delta, inQuote];
  }

  function tileColorToHex(v) {
    if (v == null) return null;
    const n = Number(v);
    if (!Number.isFinite(n)) return null;
    const r = (n >>> 24) & 255, g = (n >>> 16) & 255, b = (n >>> 8) & 255;
    if (r === 0 && g === 0 && b === 0) return null;
    const h = x => x.toString(16).padStart(2, '0');
    return '#' + h(r) + h(g) + h(b);
  }

  function unquote(v) {
    v = v.trim();
    if (v.length >= 2 && v[0] === '"' && v[v.length - 1] === '"') v = v.slice(1, -1);
    return v.split('\\"').join('"');
  }

  function count(s, ch) { return s.split(ch).length - 1; }

  function parseNk(text, source) {
    const lines = text.split(/\r?\n/);
    let i = 0, uid = 0, total = 0;
    const nodes = [], edges = [], backdrops = [];
    let rootKnobs = {};

    function readBlock(header) {
      const knobs = {};
      let [depth, inQuote] = braceDelta(header, false);
      while (depth > 0 && i < lines.length) {
        const line = lines[i++];
        if (depth === 1 && !inQuote) {
          const km = KNOB_RE.exec(line);
          if (km) {
            const k = km[1];
            let v = km[2];
            if (!KNOB_BLACKLIST.has(k) && !(k in knobs)) {
              if (v.length > 240) v = v.slice(0, 240) + ' …';
              else if (count(v, '{') > count(v, '}')) v += ' …';
              knobs[k] = v;
            }
          }
        }
        const [d, q] = braceDelta(line, inQuote);
        inQuote = q; depth += d;
      }
      return knobs;
    }

    function nInputs(knobs, cls) {
      if ('inputs' in knobs) {
        const m = knobs.inputs.match(/\d+/g);
        return m ? m.reduce((a, b) => a + parseInt(b, 10), 0) : 1;
      }
      return ZERO_INPUT.has(cls) ? 0 : 1;
    }

    function makeNode(cls, knobs) {
      uid++;
      const node = {
        id: uid, class: cls,
        name: unquote(knobs.name || cls),
        x: parseFloat(knobs.xpos || 0) || 0,
        y: parseFloat(knobs.ypos || 0) || 0,
        type: cls === 'BackdropNode' ? 'backdrop' : 'node',
      };
      const color = tileColorToHex(knobs.tile_color);
      if (color) node.color = color;
      let label = unquote(knobs.label || '').replace(/<[^>]+>/g, '').trim();
      if (label) node.label = label.slice(0, 200);
      if (cls === 'BackdropNode') {
        node.w = parseFloat(knobs.bdwidth || 200);
        node.h = parseFloat(knobs.bdheight || 200);
        node.fontSize = parseFloat(knobs.note_font_size || 20);
      }
      if (cls === 'StickyNote') node.fontSize = parseFloat(knobs.note_font_size || 11);
      if (cls === 'Read' && 'file' in knobs) node.file = unquote(knobs.file).slice(-60);
      const panel = {};
      let cnt = 0;
      for (const k of Object.keys(knobs)) {
        if (INTERNAL_KNOBS.has(k)) continue;
        if (cnt++ >= 48) break;
        panel[k] = knobs[k].slice(0, 200);
      }
      if (cnt) node.knobs = panel;
      return node;
    }

    let stack = [], named = {};
    let groupDepth = 0, groupFrames = [], currentGroup = null, groupChildren = 0;

    while (i < lines.length) {
      const line = lines[i++];
      const stripped = line.trim();
      if (!stripped) continue;

      let m = SET_RE.exec(line);
      if (m) {
        const k = parseInt(m[2], 10);
        named[m[1]] = stack.length > k ? stack[stack.length - 1 - k] : null;
        continue;
      }
      m = PUSH_RE.exec(line);
      if (m) {
        const ref = m[1];
        if (ref === '0') stack.push(null);
        else if (ref[0] === '$') stack.push(named[ref.slice(1)] ?? null);
        else stack.push(null);
        continue;
      }
      if (stripped === 'end_group') {
        if (groupFrames.length) {
          [stack, named] = groupFrames.pop();
          groupDepth--;
          if (groupDepth === 0 && currentGroup) {
            currentGroup.children = groupChildren;
            currentGroup = null;
          }
        }
        continue;
      }
      m = NODE_HEADER.exec(line);
      if (m) {
        const cls = m[1];
        const knobs = readBlock(line);
        total++;
        if (cls === 'Root') {
          rootKnobs = {};
          for (const k of Object.keys(knobs))
            if (ROOT_KNOBS.has(k)) rootKnobs[k] = unquote(knobs[k]);
          continue;
        }
        if (groupDepth > 0) {
          groupChildren++;
          const nIn = nInputs(knobs, cls);
          for (let k = 0; k < Math.min(nIn, stack.length); k++) stack.pop();
          stack.push(null);
          if (cls === 'Group') {
            groupFrames.push([stack, named]);
            stack = []; named = {};
            groupDepth++;
          }
          continue;
        }
        const node = makeNode(cls, knobs);
        const nIn = nInputs(knobs, cls);
        const kind = cls === 'Viewer' ? 2 : (knobs.hide_input === 'true' ? 1 : 0);
        for (let k = 0; k < Math.min(nIn, stack.length); k++) {
          const src = stack.pop();
          if (src !== null && src !== undefined && node.type !== 'backdrop') {
            const e = [src, node.id];
            if (kind) e.push(kind);
            edges.push(e);
          }
        }
        stack.push(node.type !== 'backdrop' ? node.id : null);
        if (node.type === 'backdrop') backdrops.push(node); else nodes.push(node);
        if (cls === 'Group') {
          groupFrames.push([stack, named]);
          stack = []; named = {};
          groupDepth = 1; currentGroup = node; groupChildren = 0;
        }
        continue;
      }
      // unknown directive that may open a block
      let [d, q] = braceDelta(line, false);
      while (d > 0 && i < lines.length) {
        const r = braceDelta(lines[i++], q);
        d += r[0]; q = r[1];
      }
    }

    return {
      nodes, edges, backdrops, root: rootKnobs,
      stats: { nodes: nodes.length, edges: edges.length,
        backdrops: backdrops.length, totalParsed: total },
      source,
    };
  }

  root.parseNk = parseNk;
  if (typeof module !== 'undefined' && module.exports) module.exports = { parseNk };
})(typeof window !== 'undefined' ? window : globalThis);
