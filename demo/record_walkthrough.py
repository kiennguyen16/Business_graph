"""Record a captioned walkthrough of the deployed Streamlit demo."""
import re
import shutil
import subprocess
from pathlib import Path
from time import monotonic

from playwright.sync_api import TimeoutError as PlaywrightTimeout, expect, sync_playwright

URL = "https://kien-nguyen-graph.streamlit.app/"
OUTPUT = Path(__file__).resolve().parents[1] / "deploy" / "video"
SIZE = {"width": 1600, "height": 900}
WAKE = re.compile(r"wake|back up", re.I)
CAPTION_JS = """({text, card}) => {
    document.getElementById('walkthrough-caption')?.remove();
    if (!text) return;
    const caption = document.createElement('div');
    caption.id = 'walkthrough-caption';
    caption.textContent = text;
    caption.style.cssText = `
        position:fixed; z-index:2147483647; bottom:0; left:0; right:0;
        box-sizing:border-box; pointer-events:none; white-space:pre-line;
        color:white; background:#112337; border-top:6px solid #F15B06;
        padding:20px 48px; font:600 30px/1.32 system-ui,sans-serif;
    `;
    if (card) caption.style.cssText += `
        top:0; display:grid; place-content:center; text-align:center;
        padding:0 180px; font-size:44px; border-top-width:12px;
    `;
    document.body.append(caption);
}"""


def ready(page, app):
    title = app.get_by_role("heading", name="AU/NZ Business Graph", exact=True)
    deadline = monotonic() + 240
    while not title.is_visible():
        if monotonic() >= deadline:
            raise RuntimeError("The Streamlit app did not become ready within four minutes.")
        for surface in (page, app):
            wake = surface.get_by_role("button", name=WAKE).first
            if wake.is_visible():
                wake.click()
        page.wait_for_timeout(500)


def settled(page, app):
    # Allow the websocket to announce the rerun before checking for stale elements.
    page.wait_for_timeout(350)
    expect(app.get_by_test_id("stStatusWidget")).to_be_hidden(timeout=15000)
    expect(app.locator('[data-stale="true"]:visible').first).to_be_hidden(timeout=15000)


def center(locator):
    locator.evaluate("(node) => node.scrollIntoView({block:'center', behavior:'smooth'})")


def record(page, started):
    app = page.frame_locator('iframe[src*="/~/+/"]')
    page.goto(URL, wait_until="domcontentloaded")
    ready(page, app)
    settled(page, app)
    clips, skipped = [], []

    def caption(text=None, card=False):
        page.evaluate(CAPTION_JS, {"text": text, "card": card})

    def hold(seconds):
        start = monotonic() - started
        page.wait_for_timeout(seconds * 1000)
        clips.append((start, monotonic() - started))

    def scene(name, text, prepare=None, followups=(), card=False):
        caption()
        try:
            if prepare:
                prepare()
                settled(page, app)
            caption(text, card)
            hold(6)
        except (PlaywrightTimeout, AssertionError) as exc:
            skipped.append(name)
            print(f"Skipped {name}: {str(exc).splitlines()[0]}", flush=True)
            caption()
            hold(6)
            for _ in followups:
                hold(5)
            return
        for label, action in followups:
            try:
                action()
                hold(5)
            except (PlaywrightTimeout, AssertionError) as exc:
                skipped.append(label)
                print(f"Skipped {label}: {str(exc).splitlines()[0]}", flush=True)
                caption()
                hold(5)
        print(f"Recorded {name}", flush=True)

    def open_evidence(pattern):
        panel = app.locator("summary").filter(has_text=pattern)
        if not panel.evaluate("(node) => node.closest('details').open"):
            panel.click()
        return panel

    def resolve(button, query, result):
        app.get_by_role("button", name=button, exact=True).click()
        expect(app.get_by_role("textbox", name=re.compile("Name, optionally"))).to_have_value(query)
        settled(page, app)
        badge = app.locator(".status-badge")
        expect(badge).to_contain_text(result)
        center(badge)

    def cba():
        resolve("CBA", "Commonwealth Bank of Australia", "RESOLVED")
        open_evidence(re.compile(r"#1\s+COMMONWEALTH BANK OF AUSTRALIA"))

    def csc():
        resolve("CSC (near-name trap)", "Commonwealth Superannuation Corporation", "RESOLVED")
        panel = open_evidence(re.compile(r"#\d+\s+COMMONWEALTH BANK OF AUSTRALIA"))
        center(panel)

    def cba_abn():
        resolve("CBA + ABN", "Commonwealth Bank of Aust ABN 48 123 123 124", "RESOLVED")
        expect(app.get_by_test_id("stAlert").first).to_contain_text("EXACT_ABN")

    def navigate(name, marker):
        app.get_by_test_id("stSidebar").get_by_role("button", name=name, exact=True).click()
        expect(app.get_by_role("heading", name=name, exact=True)).to_be_visible()
        expect(marker).to_be_visible()
        center(marker)

    def entity(key, name, marker, *, graph=False):
        heading = app.get_by_role("heading", name=re.compile(name, re.I))
        field = app.get_by_role("textbox", name=re.compile("Canonical key"))
        if not field.is_visible():
            navigate("Entity", field)
        if field.input_value() != key:
            field.fill(key)
            field.press("Enter")
        expect(heading).to_be_visible()
        settled(page, app)
        if graph:
            load = app.get_by_role("button", name="Load the graph view (about a minute)")
            if load.is_visible():
                load.click()
                expect(app.get_by_text(re.compile(r"^Graph view"))).to_be_visible(timeout=150000)
                settled(page, app)
        center(marker)

    inbound = app.get_by_text(re.compile(r"^Inbound links"))
    bans = app.get_by_text(re.compile(r"^Bans: [1-9]"))
    notices = app.get_by_text(re.compile(r"^ACCC / regulator notices: [1-9]"))
    source = app.get_by_role("combobox", name="Source")
    refusals = "Banned orgs and ACCC notices the matcher refused to attach, with reasons."

    def filter_abstentions(value):
        caption()
        source.click()
        app.get_by_role("option", name=value, exact=True).click()
        settled(page, app)
        center(source)

    def exposure():
        caption()
        app.get_by_role("button", name="Run group_exposure", exact=True).click()
        result = app.get_by_text(re.compile(r"^Foreign-controlled licensees:"))
        expect(result).to_be_visible(timeout=15000)
        settled(page, app)
        center(result)
        caption("Ultimate parent: 6 hops to Citigroup Inc, bounded and cycle-safe, agrees with GLEIF.")

    scene("Title", "AU/NZ business graph: resolve messy company references, explain why, refuse when unsure.")
    scene("CBA", "Exact normalised name. Every decision carries its evidence: features, gates, and the SQL that found it.",
          cba,
          (("CBA gates", lambda: center(app.get_by_text("Gates", exact=True).first)),
           ("CBA SQL", lambda: center(app.get_by_text("Query text that produced this candidate").first))))
    scene("CSC", "The brief's trap: similar name, unrelated entity. Embedding similarity is high, but BANK vs SUPERANNUATION fails the distinctive-token gate.",
          csc)
    scene("CBA + ABN", "An identifier beats any name: EXACT_ABN.",
          cba_abn)
    scene("Rio Tinto plc", "A UK plc is not Rio Tinto Limited: abstains with JURISDICTION_MISMATCH. A wrong link is worse than no link.",
          lambda: resolve("Rio Tinto plc (foreign)", "Rio Tinto plc", "JURISDICTION_MISMATCH"))
    scene("eDreams", "Not in the graph: abstains with an empty candidate list.",
          lambda: resolve("eDreams (not in graph)", "Vacaciones eDreams", "NO_CANDIDATE"))
    scene("Entity", "Click through: identifiers, the source records behind it, licences, bans, aliases, parents and subsidiaries.",
          lambda: entity("urn:abn:48123123124", "Commonwealth Bank of Australia",
                         app.get_by_role("heading", name=re.compile("Commonwealth Bank of Australia", re.I))),
          (("Entity source records", lambda: center(app.get_by_text("Source records behind it").first)),
           ("Entity graph facts", lambda: center(app.get_by_text("Parents (direct)", exact=False).first))))
    scene("M.A.I Pacific ban",
          "Named test 2: a ban is an accusation. It attaches only by an exact ACN; name-only matches for banned orgs need 0.97 and abstain otherwise.",
          lambda: entity("urn:abn:77095393007", r"M\.A\.I PACIFIC", bans, graph=True),
          (("M.A.I Pacific inbound link", lambda: center(inbound)),))
    scene("DYSCK notices", "ACCC notices attach by the ACN printed on the register, never by name similarity.",
          lambda: entity("urn:abn:93600485194", "DYSCK", notices, graph=True))
    scene("Traversals", "Ultimate parent: 6 hops to Citigroup Inc, bounded and cycle-safe, agrees with GLEIF.",
          lambda: navigate("Traversals", app.get_by_text(re.compile(r"GLEIF's own ultimate-parent edge")).first),
          (("Foreign-controlled licensees", exposure),
           ("Group exposure", lambda: center(app.get_by_text(
               re.compile(r"^Licensed entities in the same group as a flagged entity:")
           )))))
    def banned_refusals():
        filter_abstentions("asic_banned_org")
        caption(refusals)

    scene("ACCC abstentions", refusals,
          lambda: (navigate("Abstentions", source), filter_abstentions("accc_notice")),
          (("Banned organisation abstentions", banned_refusals),))
    scene("End card", "Precision-first matcher v4: 0 wrong links across 463 hand labels and two rehearsal sets.\nCode: github.com/kiennguyen16/Business_graph",
          card=True)
    return clips, skipped


def export(raw, clips):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        webm = OUTPUT / "walkthrough.webm"
        raw.replace(webm)
        return webm

    # Keep the reading pauses and omit loading and rerun delays.
    filters = [
        f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{i}]"
        for i, (start, end) in enumerate(clips)
    ]
    inputs = "".join(f"[v{i}]" for i in range(len(clips)))
    filters.append(f"{inputs}concat=n={len(clips)}:v=1:a=0[out]")
    mp4 = OUTPUT / "walkthrough.mp4"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
         "-filter_complex", ";".join(filters), "-map", "[out]", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)],
        check=True,
    )
    raw.unlink()
    return mp4


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport=SIZE, record_video_dir=OUTPUT, record_video_size=SIZE)
        context.set_default_timeout(10000)
        started = monotonic()
        page = context.new_page()
        try:
            clips, skipped = record(page, started)
        finally:
            context.close()
            browser.close()
        raw = page.video.path()
    video = export(raw, clips)
    print(f"Wrote {video} ({video.stat().st_size:,} bytes)")
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1", str(video)], check=True)
    print("Skipped: " + (", ".join(skipped) if skipped else "none"))


if __name__ == "__main__":
    main()
