// Ghost Handler Design Bridge — Figma plugin main thread.
//
// Two operations, both driven by pasted JSON (plugins run sandboxed with no
// network unless allowed, so paste keeps this zero-dependency):
//   1. Import design tokens  -> creates/updates Figma paint styles named
//      "gh/<group>/<...>/<token>" from design/tokens.json.
//   2. Stamp HUD mockup      -> reads design/figma/manifest.json and lays out
//      a true-to-size frame per widget on the canvas, named by widget id.

function flattenColorTokens(node, path, out) {
  Object.keys(node || {}).forEach(function (key) {
    var value = node[key];
    var next = path.concat(key);
    if (typeof value === "string" && value.charAt(0) === "#") {
      out.push({ name: next.join("/"), hex: value });
    } else if (value && typeof value === "object") {
      flattenColorTokens(value, next, out);
    }
  });
}

function hexToRgb(hex) {
  var h = hex.replace("#", "");
  if (h.length === 8) h = h.slice(2); // strip alpha if present (CSS #RRGGBBAA)
  var n = parseInt(h, 16);
  return {
    r: ((n >> 16) & 255) / 255,
    g: ((n >> 8) & 255) / 255,
    b: (n & 255) / 255,
  };
}

function importTokens(text) {
  var data = JSON.parse(text);
  var flat = [];
  flattenColorTokens(data.color, [], flat);
  if (flat.length === 0) throw new Error("No colors found under top-level key 'color'.");

  var created = 0, updated = 0;
  flat.forEach(function (tok) {
    var styleName = "gh/" + tok.name;
    var existing = figma.getLocalPaintStyles().filter(function (s) { return s.name === styleName; })[0];
    var paint = { type: "SOLID", color: hexToRgb(tok.hex) };
    if (existing) {
      existing.paints = [paint];
      updated += 1;
    } else {
      figma.createPaintStyle();
      var style = figma.getLocalPaintStyles()[figma.getLocalPaintStyles().length - 1];
      style.name = styleName;
      style.paints = [paint];
      created += 1;
    }
  });
  figma.notify("Ghost Handler: " + created + " styles created, " + updated + " updated.");
}

function stampWidgets(text) {
  var manifest = JSON.parse(text);
  var x = 0, y = 0, rowHeight = 0;
  var maxRowWidth = 2200;
  var made = 0;

  manifest.widgets.forEach(function (w) {
    var frame = figma.createFrame();
    frame.name = "widget/" + w.id;
    frame.resize(w.w, w.h);
    frame.x = x; frame.y = y;
    frame.fills = [{ type: "SOLID", color: hexToRgb("#111823") }];
    frame.strokes = [{ type: "SOLID", color: hexToRgb("#233042") }];
    frame.strokeWeight = 1;
    frame.cornerRadius = 14;

    var label = figma.createText();
    label.characters = w.name + "\n" + w.w + "×" + w.h + " · " + w.zone;
    label.fontSize = 12;
    label.fills = [{ type: "SOLID", color: hexToRgb("#8B98A9") }];
    label.x = 14; label.y = 14;
    frame.appendChild(label);

    made += 1;
    x += w.w + 40;
    rowHeight = Math.max(rowHeight, w.h);
    if (x > maxRowWidth) { x = 0; y += rowHeight + 40; rowHeight = 0; }
  });

  figma.viewport.scrollAndZoomIntoView(figma.currentPage.children);
  figma.notify("Ghost Handler: stamped " + made + " widget frames.");
}

figma.showUI(__html__, { width: 360, height: 420 });

figma.ui.onmessage = function (msg) {
  try {
    if (msg.type === "import-tokens") importTokens(msg.text);
    else if (msg.type === "stamp-widgets") stampWidgets(msg.text);
    else if (msg.type === "close") figma.closePlugin();
  } catch (err) {
    figma.notify("Ghost Handler plugin error: " + err.message);
  }
};
