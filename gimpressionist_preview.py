#!/usr/bin/env python3
"""Adjust GIMPressionist settings in a local browser and render with GIMP 3."""

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from threading import Lock
from urllib.parse import unquote, urlsplit
import webbrowser


def select(key, label, default, options):
    return dict(key=key, label=label, default=default, options=options)


def slider(key, label, default, low, high, step=1):
    return dict(key=key, label=label, default=default, low=low, high=high, step=step)


def toggle(key, label, default=0):
    return dict(key=key, label=label, default=default, toggle=True)


def assets(folder, names):
    return [(f"{folder}/{name}", name.rsplit(".", 1)[0]) for name in names.split()]


MAPPING = [(0, "Value"), (1, "Radius"), (2, "Random"), (3, "Radial"),
           (4, "Flowing"), (5, "Hue"), (6, "Adaptive")]
GROUPS = [
    ("Brush & size", [
        select("selectedbrush", "Brush shape", "Brushes/paintbrush01.pgm", assets("Brushes",
            "arrow01.pgm ball.ppm blob.ppm box.ppm chalk01.pgm cone.ppm "
            "crayon01.pgm crayon02.pgm crayon03.pgm crayon04.pgm crayon05.pgm crayon06.pgm "
            "crayon07.pgm crayon08.pgm defaultbrush.pgm dribble.pgm fabric.pgm fabric01.pgm "
            "fabric02.pgm flower01.pgm flower02.pgm flower03.pgm flower04.pgm grad01.pgm "
            "grad02.pgm grad03.pgm heart.ppm leaf01.pgm paintbrush01.pgm paintbrush02.pgm "
            "paintbrush03.pgm paintbrush04.pgm paper01.pgm paper02.pgm paper03.pgm paper04.pgm "
            "pentagram.pgm scribble.pgm shape01.pgm shape02.pgm shape03.pgm shape04.pgm "
            "snow1.pgm sphere.ppm splat1.pgm splat2.pgm splat3.pgm spunge01.pgm spunge02.pgm "
            "spunge03.pgm spunge04.pgm spunge05.pgm strange01.pgm thegimp.pgm torus.ppm "
            "wavy.pgm weave.pgm worm.pgm")),
        slider("sizefirst", "Minimum size", 9, 1, 120),
        slider("sizelast", "Maximum size", 24, 1, 120),
        slider("sizenum", "Size variants", 3, 1, 12),
        select("sizetype", "Size mapping", 2, MAPPING),
        slider("brushaspect", "Aspect ratio", 0, -1, 1, 0.05),
        slider("brushrelief", "Brush relief", 12, 0, 100),
    ]),
    ("Orientation & placement", [
        select("orienttype", "Orientation", 2, MAPPING),
        slider("orientnum", "Directions", 12, 1, 30),
        slider("orientfirst", "Start angle", 0, 0, 360),
        slider("orientlast", "Angle span", 360, 0, 360),
        select("placetype", "Placement", 0, [(0, "Random"), (1, "Evenly distributed")]),
        slider("brushdensity", "Stroke density", 18, 1, 50),
        toggle("placecenter", "Center bias"),
    ]),
    ("Paper", [
        select("selectedpaper", "Paper texture", "Paper/canvas2.pgm", assets("Paper",
            "bricks.pgm bricks2.pgm burlap.pgm canvas2.pgm defaultpaper.pgm "
            "marble.pgm marble2.pgm stone.pgm struc.pgm")),
        slider("paperscale", "Paper scale", 50, 3, 150),
        slider("paperrelief", "Paper relief", 18, 0, 100),
        toggle("paperinvert", "Invert texture"),
        toggle("paperoverlay", "Overlay texture"),
    ]),
    ("Color & finish", [
        select("colortype", "Stroke color", 0, [(0, "Average under brush"), (1, "Center of brush")]),
        slider("colornoise", "Color noise", 0, 0, 100),
        select("generalbgtype", "Background", 0, [(0, "Solid"), (1, "Keep original"), (2, "From paper")]),
        dict(key="color", label="Background color", default="#000000", color=True),
        slider("generaldarkedge", "Edge darken", 0.05, 0, 1, 0.05),
        toggle("generalpaintedges", "Paint edges", 1),
    ]),
]
FIELDS = {item["key"]: item for _, group in GROUPS for item in group}
MAX_UPLOAD = 100 * 1024 * 1024
SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".tif", ".tiff", ".bmp", ".gif", ".xcf"}
PREVIEW_SIZES = (480, 800, 1200)
BATCH = "import os, runpy; runpy.run_path(os.environ['GIMP_PREVIEW_SCRIPT'])['render']()"


def validate_settings(values):
    if not isinstance(values, dict) or values.keys() != FIELDS.keys():
        raise ValueError("The preview settings are incomplete. Reload the page and try again.")
    settings = {}
    for key, field in FIELDS.items():
        value = values[key]
        if "options" in field:
            valid = value in [option for option, _ in field["options"]]
        elif field.get("toggle"):
            valid = value in (0, 1)
        elif field.get("color"):
            valid = isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value)
        else:
            valid = type(value) in (int, float) and field["low"] <= value <= field["high"]
        if not valid:
            raise ValueError(f"Check the value for {field['label']}.")
        settings[key] = value[1:] if field.get("color") else value
    if settings["sizefirst"] > settings["sizelast"]:
        raise ValueError("Minimum brush size needs to be at or below maximum brush size.")
    return settings


def find_gimp(explicit):
    names = ("gimp-console-3.0.exe", "gimp-console.exe", "gimp-3.0.exe", "gimp.exe",
             "gimp-console-3.0", "gimp-console", "gimp-3.0", "gimp")
    if explicit:
        candidate = shutil.which(explicit)
        if candidate is None and Path(explicit).expanduser().is_file():
            candidate = str(Path(explicit).expanduser().resolve())
        if candidate is None:
            raise ValueError(f"GIMP executable not found: {explicit}")
        return candidate
    candidates = [path for name in names if (path := shutil.which(name))]
    if sys.platform == "win32":
        roots = [Path(os.environ[var]) for var in ("ProgramFiles", "LOCALAPPDATA", "ProgramFiles(x86)")
                 if os.environ.get(var)]
        for root in roots:
            for pattern in ("GIMP*/bin", "Programs/GIMP*/bin"):
                for folder in sorted(root.glob(pattern)):
                    candidates.extend(str(folder / name) for name in names if (folder / name).is_file())
    if sys.platform == "darwin":
        roots = (Path("/Applications"), Path.home() / "Applications")
        for root in roots:
            for app in sorted(root.glob("GIMP*.app")):
                candidates.extend(str(path) for path in sorted((app / "Contents/MacOS").glob("gimp*"))
                                  if path.is_file() and os.access(path, os.X_OK))
    for candidate in dict.fromkeys(candidates):
        try:
            version = subprocess.run([candidate, "--version"], capture_output=True, text=True,
                                     errors="replace", timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if version.returncode == 0 and "version 3." in version.stdout + version.stderr:
            return candidate
    raise ValueError("GIMP 3 was not found. Install GIMP 3 or pass --gimp with the path to its executable.")



class Preview:
    def __init__(self, folder, gimp):
        self.folder = folder
        self.gimp = gimp
        self.token = secrets.token_urlsafe(32)
        self.lock = Lock()
        self.image_name = ""
        self.source = None
        self.latest = None

    def upload(self, name, stream, length):
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
        suffix = Path(name).suffix.lower()
        if suffix not in SUFFIXES:
            raise ValueError("Choose a JPG, PNG, WebP, AVIF, TIFF, GIF, BMP, or XCF image.")
        if length <= 0 or length > MAX_UPLOAD:
            raise ValueError("Choose a nonempty image up to 100 MB.")
        with tempfile.NamedTemporaryFile(dir=self.folder, suffix=suffix, delete=False) as file:
            new_source = Path(file.name)
            try:
                while length:
                    chunk = stream.read(min(length, 1024 * 1024))
                    if not chunk:
                        raise ValueError("The image upload ended early. Choose the image again.")
                    file.write(chunk)
                    length -= len(chunk)
            except Exception:
                file.close()
                new_source.unlink(missing_ok=True)
                raise
        if self.source:
            self.source.unlink()
        self.source = new_source
        self.image_name = name
        self.clear_render()
        return {"name": name}

    def clear_render(self):
        if self.latest:
            shutil.rmtree(self.latest)
            self.latest = None

    def generate(self, payload):
        if not self.source:
            raise ValueError("Open an image first.")
        size = payload.get("size")
        if size not in PREVIEW_SIZES:
            raise ValueError("Choose a preview resolution.")
        settings = validate_settings(payload.get("settings"))
        job = Path(tempfile.mkdtemp(dir=self.folder))
        request = job / "request.json"
        request.write_text(json.dumps({"source": str(self.source), "size": size, "settings": settings}),
                           encoding="utf-8")
        env = os.environ.copy()
        env.update(GIMP3_DIRECTORY=str(self.folder / "profile"),
                   GIMP_PREVIEW_REQUEST=str(request), GIMP_PREVIEW_SCRIPT=str(Path(__file__).resolve()))
        try:
            with (job / "render.log").open("wb") as log:
                result = subprocess.run(
                    [self.gimp, "--new-instance", "--no-interface", "--console-messages",
                     "--batch-interpreter=python-fu-eval", "--batch", BATCH, "--quit"],
                    env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
            outcome = job / "result.json"
            if result.returncode != 0 or not outcome.is_file():
                log = (job / "render.log").read_text(encoding="utf-8", errors="replace")
                print(log[-3000:], file=sys.stderr)
                raise ValueError("GIMP did not render the preview. Check the PowerShell or terminal output.")
            result = json.loads(outcome.read_text(encoding="utf-8"))
            if "error" in result:
                raise ValueError(result["error"])
            self.clear_render()
            self.latest = job
            result["revision"] = job.name
            return result
        except subprocess.TimeoutExpired as error:
            raise ValueError("GIMP timed out. Try a smaller preview resolution.") from error
        finally:
            if self.latest != job:
                shutil.rmtree(job, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def respond(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data, status=HTTPStatus.OK):
        self.respond(status, "application/json; charset=utf-8", json.dumps(data).encode("utf-8"))

    def do_GET(self):
        if self.headers.get("Host") != self.server.host:
            return self.send_error(HTTPStatus.FORBIDDEN)
        route = urlsplit(self.path)
        if route.path == "/":
            page = PAGE.replace("__GROUPS__", json.dumps(GROUPS)).replace("__TOKEN__", self.server.preview.token)
            return self.respond(HTTPStatus.OK, "text/html; charset=utf-8", page.encode("utf-8"))
        if route.path in ("/original.png", "/preview.png"):
            preview = self.server.preview
            with preview.lock:
                if preview.latest and route.query == preview.latest.name:
                    pixels = (preview.latest / route.path[1:]).read_bytes()
                else:
                    return self.send_error(HTTPStatus.NOT_FOUND)
            return self.respond(HTTPStatus.OK, "image/png", pixels)
        return self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        preview = self.server.preview
        if (self.headers.get("Host") != self.server.host or
                self.headers.get("Origin") != f"http://{self.server.host}" or
                self.headers.get("X-Preview-Token") != preview.token):
            return self.send_error(HTTPStatus.FORBIDDEN)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            with preview.lock:
                if self.path == "/image":
                    response = preview.upload(unquote(self.headers.get("X-Image-Name", "")), self.rfile, length)
                elif self.path == "/render" and 0 < length <= 8192:
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError("Invalid preview settings.")
                    response = preview.generate(payload)
                else:
                    return self.send_error(HTTPStatus.NOT_FOUND)
        except (OSError, ValueError) as error:
            return self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        return self.send_json(response)


def render():
    # GIMP runs this function in its embedded Python interpreter.
    import gi
    gi.require_version("Gimp", "3.0")
    from gi.repository import Gimp, Gio

    request_path = Path(os.environ["GIMP_PREVIEW_REQUEST"])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    job = request_path.parent
    mode = Gimp.RunMode.NONINTERACTIVE
    pdb = Gimp.get_pdb()

    def run(procedure, config, message):
        result = procedure.run(config)
        if result.index(0) != Gimp.PDBStatusType.SUCCESS:
            raise RuntimeError(message)

    def export(image, name):
        config = png.create_config()
        config.set_property("run-mode", mode)
        config.set_property("image", image)
        config.set_property("file", Gio.File.new_for_path(str(job / name)))
        config.set_property("compression", 3)
        for key in ("include-exif", "include-iptc", "include-xmp", "include-comment"):
            config.set_property(key, False)
        run(png, config, "GIMP could not export the PNG.")

    image = None
    try:
        effect = pdb.lookup_procedure("plug-in-gimpressionist")
        png = pdb.lookup_procedure("file-png-export")
        if effect is None or png is None:
            raise RuntimeError("This installation of GIMP needs the GIMPressionist and PNG plug-ins.")
        image = Gimp.file_load(mode, Gio.File.new_for_path(request["source"]))
        if image is None:
            raise RuntimeError("GIMP could not read this image.")
        image.undo_disable()
        if image.get_base_type() != Gimp.ImageBaseType.RGB and not image.convert_rgb():
            raise RuntimeError("GIMP could not convert this image to RGB.")
        if image.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE) is None:
            raise RuntimeError("This image has no visible layers.")
        width, height = image.get_width(), image.get_height()
        scale = min(1, request["size"] / max(width, height))
        if scale < 1:
            width, height = max(1, round(width * scale)), max(1, round(height * scale))
            if not image.scale(width, height):
                raise RuntimeError("GIMP could not scale this image.")

        settings = request["settings"]
        # GIMPressionist places a border equal to the largest rotated brush.
        # Limit unsafe combinations on small or unusually narrow images.
        if min(width, height) < 16 or settings["sizelast"] > min(width, height):
            raise RuntimeError("The image is too small for this brush size. Reduce maximum size or increase preview resolution.")

        Gimp.Selection.none(image)
        export(image, "original.png")
        preset_path = Path(Gimp.directory()) / "gimpressionist" / "Presets" / "local-preview"
        preset_path.parent.mkdir(parents=True, exist_ok=True)
        preset_path.write_text("Preset\nbrushgamma=1\n" + "".join(
            f"{key}={value}\n" for key, value in settings.items()), encoding="ascii")
        config = effect.create_config()
        config.set_property("run-mode", mode)
        config.set_property("image", image)
        config.set_core_object_array("drawables", [image.get_layers()[0]])
        config.set_property("preset", preset_path.name)
        run(effect, config, "GIMPressionist could not apply these settings.")
        export(image, "preview.png")
        outcome = {"width": width, "height": height}
    except RuntimeError as error:
        outcome = {"error": str(error)}
    finally:
        if image:
            image.delete()
    (job / "result.json").write_text(json.dumps(outcome), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gimp", help="path to GIMP 3's executable")
    parser.add_argument("--no-open", action="store_true", help="print the local URL without opening the browser")
    args = parser.parse_args()
    try:
        gimp = find_gimp(args.gimp)
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    with tempfile.TemporaryDirectory(prefix="gimpressionist-preview-") as scratch:
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            server.daemon_threads = False
            server.preview = Preview(Path(scratch), gimp)
            server.host = f"127.0.0.1:{server.server_port}"
            url = f"http://{server.host}/"
            print(f"GIMPressionist Preview running at {url}\nClose this terminal or press Ctrl+C to stop.", flush=True)
            if not args.no_open:
                webbrowser.open(url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GIMPressionist Preview</title>
<style>
:root { color-scheme:dark; font:15px 'Inter', 'Segoe UI', system-ui, sans-serif; background:#151515;
  color:#f0eee9; --surface:#1d1d1d; --line:#363431; --muted:#bdb7ad; --accent:#f5bd83; }
* { box-sizing:border-box; }
body { margin:0; }
button,input,select { font:inherit; }
button, select, input[type=number], .download { background:#282725; color:inherit; border:1px solid #494642;
  border-radius:7px; }
button, .download { cursor:pointer; font-weight:650; padding:9px 14px; text-decoration:none; white-space:nowrap; }
button:hover:not(:disabled), .download:hover { border-color:var(--accent); }
button:disabled { opacity:.46; cursor:default; }
button.primary { color:#211a12; background:var(--accent); border-color:var(--accent); }
:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
[hidden] { display:none !important; }
header { min-height:76px; display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between;
  border-bottom:1px solid var(--line); padding:14px 24px; gap:14px; }
h1 { font-size:clamp(21px,3.5vw,29px); letter-spacing:-.034em; margin:0; }
.toolbar { display:flex; flex-wrap:wrap; gap:9px; align-items:center; }
.layout { display:grid; grid-template-columns:320px minmax(0,1fr); min-height:calc(100vh - 76px); }
aside { background:var(--surface); border-right:1px solid var(--line); min-width:0; }
.side-head { display:flex; align-items:center; justify-content:space-between; padding:16px 18px 13px; }
.side-head h2 { margin:0; font-size:16px; }
.side-head button { padding:5px 9px; font-size:13px; }
details { border-top:1px solid var(--line); }
summary { display:flex; align-items:center; gap:10px; list-style:none; cursor:pointer;
  font-weight:650; padding:14px 18px; }
summary::-webkit-details-marker { display:none; }
summary::before { content:""; width:6px; height:6px; border:solid var(--accent); border-width:0 2px 2px 0;
  transform:rotate(-45deg); }
details[open] > summary::before { transform:rotate(45deg); }
.fields { display:grid; gap:11px; padding:0 18px 16px; }
.field { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:4px 10px; min-width:0; }
.field label { color:#ddd7ce; font-size:14px; }
.field select { grid-column:1/-1; width:100%; }
select { appearance:none; height:34px; line-height:20px; padding:3px 29px 3px 9px;
  background-image:linear-gradient(45deg,transparent 50%,#d4c9bb 50%),
    linear-gradient(135deg,#d4c9bb 50%,transparent 50%);
  background-position:right 13px center,right 8px center;
  background-size:5px 5px; background-repeat:no-repeat; }
input[type=number] { width:71px; min-height:29px; text-align:right; padding:3px 5px; }
input[type=range] { grid-column:1/-1; margin:0; width:100%; }
input[type=range], input[type=checkbox] { accent-color:var(--accent); }
input[type=color] { cursor:pointer; }
.workspace { display:flex; flex-direction:column; min-width:0; padding:20px 24px; }
.meta { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:12px;
  margin-bottom:18px; }
.meta label { color:var(--muted); margin-right:7px; }
#source { font-weight:650; overflow-wrap:anywhere; }
#status { color:var(--muted); margin:5px 0 0; font-size:14px; min-height:1.25em; }
#status.error { color:#ffae9e; }
.images { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
figure { margin:0; min-width:0; border:1px solid var(--line); border-radius:10px; overflow:hidden;
  background:#121212; }
figcaption { display:flex; justify-content:space-between; padding:12px 14px; gap:6px; background:var(--surface);
  font-weight:650; }
#dimensions { font-size:13px; color:var(--muted); font-weight:400; }
.picture { position:relative; display:grid; place-items:center; aspect-ratio:1; width:100%; max-height:68vh; min-height:130px;
  color:var(--muted); text-align:center; }
.picture a { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; width:100%; height:100%; min-height:0; }
.picture img { width:100%; height:100%; object-fit:contain; display:block; }
.picture span { padding:12px; }
@media(max-width:960px) { .layout { grid-template-columns:275px minmax(0,1fr); }
  .workspace { padding:16px; } }
@media(max-width:725px) { header { padding:12px 14px; } .layout { display:flex; flex-direction:column; }
  .workspace { order:-1; padding:14px; } aside { border-right:0; border-top:1px solid var(--line); }
  .images { gap:8px; } .picture { min-height:105px; } figcaption { padding:8px; } }
</style>
</head>
<body>
<header>
  <h1>GIMPressionist Preview</h1>
  <div class="toolbar">
    <input type="file" id="file" accept=".jpg,.jpeg,.png,.webp,.avif,.tif,.tiff,.bmp,.gif,.xcf" hidden>
    <button type="button" id="choose">Open image</button>
    <button type="button" id="generate" class="primary" disabled>Generate preview</button>
    <a class="download" id="save" download hidden>Save PNG</a>
  </div>
</header>
<main class="layout">
<aside aria-label="Filter settings">
  <div class="side-head"><h2>Settings</h2><button type="button" id="reset">Reset</button></div>
  <form id="settings"></form>
</aside>
<section class="workspace" aria-label="Image comparison">
  <div class="meta">
    <div><div id="source">No image open</div><p id="status" role="status" aria-live="polite">Open a photo to start.</p></div>
    <div><label for="size">Preview size</label><select id="size">
      <option value="480">480 px</option><option value="800" selected>800 px</option><option value="1200">1,200 px</option>
    </select></div>
  </div>
  <div class="images">
    <figure><figcaption>Original <span id="dimensions"></span></figcaption>
      <div class="picture" id="original"><span>Source image</span></div></figure>
    <figure><figcaption>Filtered preview</figcaption>
      <div class="picture" id="filtered"><span>Preview appears here</span></div></figure>
  </div>
</section>
</main>
<script>
const groups = __GROUPS__;
const token = "__TOKEN__";
const get = id => document.getElementById(id);
const settings = get("settings");
const fields = new Map();
const choose = get("choose"), file = get("file"), generate = get("generate");
const size = get("size"), save = get("save"), status = get("status");
let imageName = "", busy = false, lastRendered = "";

function element(tag, props) {
  return Object.assign(document.createElement(tag), props);
}

groups.forEach(([title, group], index) => {
  const details = element("details", {open: index === 0});
  details.append(element("summary", {textContent: title}));
  const items = element("div", {className: "fields"});
  for (const field of group) {
    const row = element("div", {className: "field"});
    const id = "control-" + field.key;
    const label = element("label", {htmlFor: id, textContent: field.label});
    let input, range = null;
    if (field.options) {
      input = element("select", {id});
      for (const [value, text] of field.options) input.add(new Option(text, value));
    } else if (field.toggle || field.color) {
      input = element("input", {id, type: field.toggle ? "checkbox" : "color"});
    } else {
      const bounds = {min: field.low, max: field.high, step: field.step};
      input = element("input", {id, type: "number", required: true, ...bounds});
      range = element("input", {type: "range", ...bounds, tabIndex: -1});
      range.setAttribute("aria-label", field.label + " slider");
      input.addEventListener("input", () => {if (input.value !== "") range.value = input.value;});
      range.addEventListener("input", () => {input.value = range.value;});
    }
    row.append(label, input);
    if (range) row.append(range);
    if (field.options) label.style.gridColumn = "1/-1";
    items.append(row);
    fields.set(field.key, {field, input, range});
  }
  details.append(items);
  settings.append(details);
});

function reset() {
  for (const {field, input, range} of fields.values()) {
    if (field.toggle) input.checked = Boolean(field.default);
    else input.value = field.default;
    if (range) range.value = field.default;
  }
  settingsChanged();
}

function values() {
  return Object.fromEntries(Array.from(fields, ([key, {field, input}]) => [
    key, field.toggle ? Number(input.checked) :
         field.color || (field.options && typeof field.default === "string") ? input.value :
         (input.value === "" ? null : Number(input.value)),
  ]));
}

function requestData() {
  return {size: Number(size.value), settings: values()};
}

function statusMessage(text, error = false) {
  status.textContent = text;
  status.classList.toggle("error", error);
}

function settingsChanged() {
  fields.get("color").input.disabled = fields.get("generalbgtype").input.value !== "0";
  if (imageName && !busy && lastRendered) {
    const current = JSON.stringify(requestData()) === lastRendered;
    statusMessage(current ? "Preview ready." : "Settings changed. Generate a new preview to apply them.");
  }
}

function lockUI(locked) {
  busy = locked;
  choose.disabled = locked;
  generate.disabled = locked || !imageName;
  generate.textContent = locked ? "Working…" : "Generate preview";
}

async function post(url, body, headers) {
  const response = await fetch(url, {
    method: "POST", body, headers: {"X-Preview-Token": token, ...headers},
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "This operation failed.");
  return data;
}

function showImage(id, url, alt) {
  const link = element("a", {href: url, target: "_blank", rel: "noopener",
    title: "Open image at full preview size"});
  link.append(element("img", {src: url, alt}));
  get(id).replaceChildren(link);
}

async function renderPreview() {
  if (!imageName || !settings.reportValidity()) return;
  const payload = requestData();
  if (payload.settings.sizefirst > payload.settings.sizelast) {
    statusMessage("Minimum brush size needs to be at or below maximum brush size.", true);
    return;
  }
  lockUI(true);
  statusMessage("Rendering with GIMP…");
  try {
    const data = await post("/render", JSON.stringify(payload), {"Content-Type": "application/json"});
    const original = "/original.png?" + data.revision, preview = "/preview.png?" + data.revision;
    showImage("original", original, "Original at preview size");
    showImage("filtered", preview, "GIMPressionist result");
    get("dimensions").textContent = data.width + " × " + data.height + " px";
    save.href = preview;
    save.download = imageName.replace(/\\.[^.]+$/, "") + "-gimpressionist.png";
    save.hidden = false;
    lastRendered = JSON.stringify(payload);
    statusMessage(lastRendered === JSON.stringify(requestData()) ? "Preview ready." :
      "Settings changed during rendering. Generate again to update the preview.");
  } catch (error) {
    statusMessage(error.message, true);
  } finally {
    lockUI(false);
  }
}

choose.addEventListener("click", () => file.click());
file.addEventListener("change", async () => {
  const selected = file.files[0];
  file.value = "";
  if (!selected) return;
  lockUI(true);
  statusMessage("Opening " + selected.name + "…");
  try {
    const data = await post("/image", selected, {"X-Image-Name": encodeURIComponent(selected.name)});
    imageName = data.name;
    lastRendered = "";
    save.hidden = true;
    get("source").textContent = imageName;
    get("dimensions").textContent = "";
    get("original").replaceChildren(element("span", {textContent: "Loading image…"}));
    get("filtered").replaceChildren(element("span", {textContent: "Rendering preview…"}));
  } catch (error) {
    statusMessage(error.message, true);
    lockUI(false);
    return;
  }
  lockUI(false);
  await renderPreview();
});
generate.addEventListener("click", renderPreview);
settings.addEventListener("submit", event => {event.preventDefault(); if (!busy) renderPreview();});
settings.addEventListener("input", settingsChanged);
size.addEventListener("change", settingsChanged);
get("reset").addEventListener("click", reset);
reset();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
