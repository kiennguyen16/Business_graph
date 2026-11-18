"""Capture the deployed Streamlit walkthrough and synchronize its narration."""

import argparse
import random
import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from textwrap import wrap
from time import monotonic

import yaml
from playwright.sync_api import expect, sync_playwright

from record_walkthrough import OUTPUT, SIZE, URL, center, ready, settled
from tts import SAMPLE_RATE, duration, make_synthesizer, select_engine

FPS = 25
LEAD = 0.16
OVERLAY = """() => {
    const host = document.createElement('div');
    host.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483647';
    const root = host.attachShadow({mode:'open'});
    root.innerHTML = `
        <style>
          #cursor { position:absolute; left:0; top:0; width:29px; height:35px;
                    filter:drop-shadow(0 1px 2px #0008); }
          #card { position:absolute; bottom:44px; left:44px; max-width:820px;
                  border-left:5px solid #ff742a; border-radius:7px;
                  padding:23px 30px; background:#112337; color:#fff;
                  font:650 32px/1.2 system-ui; box-shadow:0 8px 32px #0004; }
          small { display:block; color:#e4ebf4; margin-top:8px;
                  font:450 20px/1.45 system-ui; white-space:pre-line; }
        </style>
        <svg id="cursor" viewBox="0 0 29 35" hidden>
          <path d="M2 2 L2 26 L8.5 20 L14.5 31 L19 28.5 L13 18 L23 17 Z"
                fill="#112337" stroke="#fff" stroke-width="2.3" stroke-linejoin="round"/>
        </svg>
        <div id="card" hidden><span></span><small></small></div>`;
    const cursor = root.getElementById('cursor');
    const card = root.getElementById('card');
    document.body.append(host);
    window.walkthrough = {
        move(x, y) {
            cursor.removeAttribute('hidden');
            cursor.style.transform = `translate(${x - 2}px,${y - 2}px)`;
        },
        ripple(x, y) {
            const ring = document.createElement('div');
            ring.style.cssText = `position:absolute;left:${x - 18}px;top:${y - 18}px;
                width:36px;height:36px;border:2px solid #fb781f;background:#fb781f25;
                box-sizing:border-box;border-radius:50%;`;
            root.insertBefore(ring, cursor);
            ring.animate([{transform:'scale(.35)',opacity:.9},
                          {transform:'scale(1.35)',opacity:0}],
                         {duration:480,easing:'ease-out'}).onfinish = () => ring.remove();
        },
        title(title, subtitle) {
            card.hidden = !title;
            card.firstElementChild.textContent = title;
            card.lastElementChild.textContent = subtitle;
            if (title) cursor.setAttribute('hidden', '');
        }
    };
}"""


@dataclass
class Scene:
    text: str
    audio: Path
    seconds: float
    spans: list[tuple[float, float]]

    @property
    def frames(self):
        return sum(round(end * FPS) - round(start * FPS) for start, end in self.spans)


class Walkthrough:
    def __init__(self, page, started):
        self.page = page
        self.started = started
        self.frame = page.locator('iframe[src*="/~/+/"]').first
        self.app = self.frame.content_frame
        self.point = (800, 410)
        self.jitter = random.Random(42)
        self.cuts = []

    def time(self):
        return monotonic() - self.started

    def pause(self, seconds):
        self.page.wait_for_timeout(seconds * 1000)

    def show(self, target):
        target.wait_for(state="visible")
        # Large jumps use the existing smooth scroll helper. Wheel the last
        # portion so the viewer can follow where the content lands.
        frame = self.frame.bounding_box()
        box = target.bounding_box()
        if not frame or not box:
            raise RuntimeError("Could not locate the walkthrough target on screen.")
        y = frame["y"] + frame["height"] * 0.48
        delta = box["y"] + min(box["height"], 100) / 2 - y
        if abs(delta) > frame["height"] * 1.5:
            center(target)
            self.pause(0.58)
        elif abs(delta) > 180 and frame["x"] + 0.7 * frame["width"] > box["x"]:
            self.move(frame["x"] + 0.7 * frame["width"], y, 0.27)
            for fraction in (0.10, 0.17, 0.23, 0.23, 0.17, 0.10):
                self.page.mouse.wheel(0, round(delta * fraction))
                self.pause(0.044)
            self.pause(0.12)
        box = target.bounding_box()
        if box and not (frame["y"] + 60 <= box["y"] + min(box["height"], 100) / 2
                        <= frame["y"] + frame["height"] - 24):
            center(target)
            self.pause(0.52)

    def move(self, x, y, seconds=0.72):
        x0, y0 = self.point
        started = monotonic()
        while True:
            progress = min((monotonic() - started) / seconds, 1)
            eased = progress * progress * (3 - 2 * progress)
            point = (x0 + (x - x0) * eased, y0 + (y - y0) * eased)
            self.page.mouse.move(*point)
            self.page.evaluate("([x, y]) => window.walkthrough.move(x, y)", point)
            if progress == 1:
                break
            self.pause(0.021)
        self.point = (x, y)

    def approach(self, target, *, row=False, click=False, scroll=True):
        if scroll:
            self.show(target)
        if click:
            target.click(trial=True)
        # Playwright reports iframe element boxes in the main viewport's coordinates.
        box = target.bounding_box()
        if not box:
            raise RuntimeError("Walkthrough target disappeared.")
        y = min(55, box["height"] / 2) if row else box["height"] / 2
        self.move(box["x"] + box["width"] / 2, box["y"] + y)

    def click(self, target, *, scroll=True):
        self.approach(target, click=True, scroll=scroll)
        self.page.evaluate("([x, y]) => window.walkthrough.ripple(x, y)", self.point)
        target.click()

    def hover(self, target, *, row=False):
        self.approach(target, row=row)
        self.pause(0.30)

    def wait_for_result(self, marker):
        start = self.time()
        expect(marker).to_be_visible(timeout=150000)
        settled(self.page, self.app)
        end = self.time()
        if end - start > 1.25:
            self.cuts.append((start + 0.46, end))

    def title(self, title="", subtitle=""):
        self.page.evaluate("([title, sub]) => window.walkthrough.title(title, sub)", [title, subtitle])

    def navigate(self, name):
        self.click(self.app.get_by_test_id("stSidebar").get_by_role("button", name=name, exact=True))
        self.wait_for_result(self.app.get_by_role("heading", name=name, exact=True))

    def resolve(self, query, result, *, example=None):
        field = self.app.get_by_role("textbox", name=re.compile("Name, optionally"))
        if example:
            self.click(self.app.get_by_role("button", name=example, exact=True))
        else:
            self.click(field)
            self.page.keyboard.press("ControlOrMeta+a")
            self.page.keyboard.press("Backspace")
            for char in query:
                self.page.keyboard.insert_text(char)
                self.pause(self.jitter.uniform(0.060, 0.110))
            self.page.keyboard.press("Enter")
        expect(field).to_have_value(query)
        badge = self.app.locator(".status-badge").filter(has_text=result)
        self.wait_for_result(badge)
        return badge

    def evidence(self, candidate, *, sql=False):
        panel = self.app.locator("summary").filter(has_text=candidate)
        expanded = panel.locator("xpath=ancestor::details[1]")
        if expanded.evaluate("(node) => node.open"):
            self.hover(panel)
        else:
            self.click(panel)
            expect(expanded).to_have_js_property("open", True)
        self.pause(0.38)
        self.hover(expanded.get_by_test_id("stDataFrame").first, row=True)
        if sql:
            self.hover(expanded.get_by_text("Query text that produced this candidate").first)

    def open_cba(self):
        self.click(self.app.get_by_role("button", name="Open entity urn:abn:48123123124", exact=True))
        self.wait_for_result(self.app.get_by_role("heading", name=re.compile("Commonwealth Bank of Australia", re.I)))
        self.hover(self.app.get_by_text("Source records behind it").first)

    def entity(self, key, name, marker):
        field = self.app.get_by_role("textbox", name=re.compile("Canonical key"))
        if not field.is_visible():
            self.navigate("Entity")
        self.click(field)
        field.fill(key)
        field.press("Enter")
        self.wait_for_result(self.app.get_by_role("heading", name=re.compile(name, re.I)))
        load = self.app.get_by_role("button", name="Load the graph view (about a minute)")
        if load.is_visible():
            self.click(load)
        self.wait_for_result(marker)
        self.hover(marker)

    def traversal(self):
        self.navigate("Traversals")
        self.hover(self.app.get_by_text(re.compile(r"GLEIF's own ultimate-parent edge")).first)
        self.click(self.app.get_by_role("button", name="Run group_exposure", exact=True))
        result = self.app.get_by_text(re.compile(r"^Foreign-controlled licensees:"))
        self.wait_for_result(result)
        self.hover(self.app.get_by_text(re.compile(r"^Licensed entities in the same group as a flagged entity:")))

    def abstentions(self):
        self.navigate("Abstentions")
        source = self.app.get_by_role("combobox", name="Source")
        table = self.app.locator('[data-testid="stDataFrame"]:visible').nth(1)
        self.hover(table, row=True)
        self.click(source)
        self.click(self.app.get_by_role("option", name="asic_banned_org", exact=True), scroll=False)
        self.wait_for_result(table)
        self.hover(table, row=True)

    def actions(self):
        return {
            "intro": lambda: self.title("AU/NZ Business Graph", "Resolving business identities with evidence"),
            "cba": lambda: (
                self.title(),
                self.resolve("Commonwealth Bank of Australia", "RESOLVED"),
                self.evidence(re.compile(r"#1\s+COMMONWEALTH BANK OF AUSTRALIA"), sql=True),
            ),
            "csc": lambda: (
                self.resolve("Commonwealth Superannuation Corporation", "RESOLVED"),
                self.evidence(re.compile(r"#\d+\s+COMMONWEALTH BANK OF AUSTRALIA")),
            ),
            "abn": lambda: (
                self.resolve("Commonwealth Bank of Aust ABN 48 123 123 124", "RESOLVED"),
                self.hover(self.app.get_by_test_id("stAlert").first.filter(has_text="EXACT_ABN")),
            ),
            "entity": self.open_cba,
            "rio": lambda: (
                self.navigate("Resolve"),
                self.hover(self.resolve("Rio Tinto plc", "JURISDICTION_MISMATCH", example="Rio Tinto plc (foreign)")),
            ),
            "edreams": lambda: self.hover(self.resolve("Vacaciones eDreams", "NO_CANDIDATE")),
            "ban": lambda: self.entity(
                "urn:abn:77095393007", r"M\.A\.I PACIFIC", self.app.get_by_text(re.compile(r"^Bans: [1-9]")),
            ),
            "notices": lambda: self.entity(
                "urn:abn:93600485194", "DYSCK", self.app.get_by_text(re.compile(r"^ACCC / regulator notices: [1-9]")),
            ),
            "traversal": self.traversal,
            "abstentions": self.abstentions,
            "close": lambda: self.title(
                "Precision-first matcher v4",
                "outputs/evaluation.md  |  outputs/resolution_run_20261117.md\ngithub.com/kiennguyen16/Business_graph",
            ),
        }

    def capture(self, scenes):
        self.page.goto(URL, wait_until="domcontentloaded")
        ready(self.page, self.app)
        settled(self.page, self.app)
        self.page.evaluate(OVERLAY)
        actions = self.actions()
        if list(scenes) != list(actions):
            raise ValueError("Narration IDs and walkthrough actions must match in order.")
        for name, scene in scenes.items():
            self.cuts.clear()
            start = self.time()
            print(f"Recording {name}", flush=True)
            actions[name]()
            elapsed = self.time() - start - sum(end - begin for begin, end in self.cuts)
            self.pause(max(0.5, scene.seconds + LEAD + 0.48 - elapsed))
            end = self.time()
            starts = [start, *(stop for _, stop in self.cuts)]
            ends = [*(begin for begin, _ in self.cuts), end]
            scene.spans = list(zip(starts, ends))
            print(f"Recorded {name}: {scene.frames / FPS:.2f} s", flush=True)


def srt_time(seconds):
    millis = round(seconds * 1000)
    return f"{millis // 3600000:02}:{millis // 60000 % 60:02}:{millis // 1000 % 60:02},{millis % 1000:03}"


def soundtrack(scenes, path):
    captions = []
    position = 0
    lead_samples = round(LEAD * SAMPLE_RATE)
    with wave.open(str(path), "wb") as track:
        track.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        for scene in scenes:
            samples = scene.frames * SAMPLE_RATE // FPS
            with wave.open(str(scene.audio), "rb") as clip:
                count = clip.getnframes()
                tail = samples - lead_samples - count
                if tail < 0:
                    raise RuntimeError("A recorded scene is shorter than its narration.")
                track.writeframes(b"\0\0" * lead_samples)
                track.writeframes(clip.readframes(count))
                track.writeframes(b"\0\0" * tail)

            # Keep at most two caption lines on screen. Allocate each cue a
            # share of the measured clip duration based on its word count.
            lines = wrap(scene.text, width=42, break_long_words=False, break_on_hyphens=False)
            total_words = len(scene.text.split())
            cue_start = (position + lead_samples) / SAMPLE_RATE
            for index in range(0, len(lines), 2):
                cue = "\n".join(lines[index:index + 2])
                cue_end = cue_start + scene.seconds * len(cue.split()) / total_words
                captions.append(f"{len(captions) + 1}\n{srt_time(cue_start)} --> {srt_time(cue_end)}\n{cue}\n")
                cue_start = cue_end
            position += samples
    return "\n".join(captions)


def export(ffmpeg, raw, scenes, work):
    seconds = sum(scene.frames for scene in scenes) / FPS
    if not 100 <= seconds <= 130:
        raise RuntimeError(f"Walkthrough is {seconds:.1f} s. Adjust the narration or KOKORO_SPEED and retry.")
    audio = work / "narration.wav"
    captions = soundtrack(scenes, audio)
    windows = [
        f"between(n,{round(start * FPS)},{round(end * FPS) - 1})"
        for scene in scenes for start, end in scene.spans
    ]
    video_filter = f"fps={FPS},select='{'+'.join(windows)}',setpts=N/({FPS}*TB)"
    target = work / "walkthrough_voiceover.mp4"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), "-i", str(audio),
         "-vf", video_filter, "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(target)],
        check=True,
    )
    video = OUTPUT / target.name
    target.replace(video)
    video.with_suffix(".srt").write_text(captions, encoding="utf-8")
    print(f"Wrote {video} ({seconds:.2f} s, {video.stat().st_size:,} bytes). Skipped: none.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("auto", "elevenlabs", "kokoro", "piper"), default="auto")
    args = parser.parse_args()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        parser.error("ffmpeg must be on PATH.")
    engine = select_engine(args.engine)
    print(f"TTS engine: {engine}", flush=True)
    synthesize = make_synthesizer(engine, ffmpeg)
    entries = yaml.safe_load(Path(__file__).with_name("narration.yaml").read_text(encoding="utf-8"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="voiceover-", dir=OUTPUT) as temp:
        work = Path(temp)
        scenes = {}
        for entry in entries:
            name, text = entry["id"], entry["text"]
            path = work / f"{name}.wav"
            spoken = text.replace("M.A.I.", "M A I").replace("CSCAL", "C S C A L")
            synthesize(spoken, path)
            scenes[name] = Scene(text, path, duration(path), [])
            print(f"Narration {name}: {scenes[name].seconds:.2f} s", flush=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport=SIZE, record_video_dir=work, record_video_size=SIZE)
            context.set_default_timeout(10000)
            started = monotonic()
            page = context.new_page()
            try:
                Walkthrough(page, started).capture(scenes)
            finally:
                context.close()
                browser.close()
            raw = page.video.path()
        export(ffmpeg, raw, list(scenes.values()), work)


if __name__ == "__main__":
    main()
