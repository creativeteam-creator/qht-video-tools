"""
QHT Script Generator + B-Roll Finder (Combined)
Transcript → Script (Claude API, streaming) → Keywords → B-Rolls (auto)
"""

import streamlit as st
import os
import re
import json
import subprocess
import urllib.parse
from datetime import datetime
from pathlib import Path

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="QHT Script + B-Roll Finder",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_LIBRARY    = "/Volumes/PHOTOGRAPHY/Testing B-Rolls Library"
DEFAULT_MAC_PREFIX = "/Volumes/PHOTOGRAPHY"
DEFAULT_WIN_PREFIX = r"\\QHTNAS\photography"
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".mxf", ".3gp", ".ts", ".mts",
}
METADATA_FIELDS = [
    "Keywords", "Subject", "Category", "Title",
    "XPKeywords", "TagsList", "Description",
    "LastKeywordXMP", "HierarchicalSubject",
]
STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "i", "me", "my",
    "we", "our", "you", "your", "he", "she", "it", "its", "they", "them",
    "their", "this", "that", "these", "those", "what", "which", "who",
    "whom", "when", "where", "how", "why", "not", "no", "nor", "but",
    "and", "or", "so", "if", "then", "than", "too", "very", "just",
    "about", "above", "after", "again", "all", "also", "am", "any",
    "as", "at", "back", "because", "before", "between", "both", "by",
    "come", "could", "day", "down", "each", "even", "find", "first",
    "for", "from", "get", "give", "go", "going", "good", "great",
    "here", "him", "his", "her", "hers", "in", "into", "know",
    "last", "let", "like", "long", "look", "make", "many", "more",
    "most", "much", "need", "new", "now", "of", "off", "old", "on",
    "one", "only", "other", "out", "over", "own", "part", "people",
    "place", "point", "same", "say", "see", "seem", "show", "side",
    "since", "small", "some", "something", "still", "such", "take",
    "tell", "thing", "think", "through", "time", "to", "two", "under",
    "up", "us", "use", "want", "way", "well", "with", "work", "world",
    "year", "years", "while", "video", "clip", "footage", "shot",
    "scene", "camera", "film", "roll", "b-roll",
}

# ── Session State ─────────────────────────────────────────────────────────────
for _k, _v in {
    # Tab 1 — Script + B-Roll
    "generated_script": "",
    "broll_results": [],
    "broll_keywords": [],
    "clip_data_lines": "",
    "open_status": {},
    "just_generated": False,
    # Tab 2 — B-Roll only
    "solo_results": [],
    "solo_keywords": [],
    "solo_open_status": {},
    # EDL
    "edl_generated": False,
    "edl_content": "",
    "edl_clips": [],
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── Keyword Extraction ────────────────────────────────────────────────────────
def extract_keywords_spacy(text: str) -> list[str]:
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm")
        doc = nlp(text)
        keywords: set[str] = set()
        for token in doc:
            if token.pos_ in ("NOUN", "PROPN") and not token.is_stop:
                lemma = token.lemma_.lower().strip()
                if len(lemma) > 2 and lemma not in STOPWORDS:
                    keywords.add(lemma)
        for ent in doc.ents:
            kw = ent.text.lower().strip()
            if len(kw) > 2:
                keywords.add(kw)
        return sorted(keywords)
    except Exception:
        return _extract_keywords_basic(text)


def _extract_keywords_basic(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return sorted({w for w in words if w not in STOPWORDS})


# ── ExifTool & Library ────────────────────────────────────────────────────────
def check_exiftool() -> bool:
    try:
        r = subprocess.run(["exiftool", "-ver"], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _read_metadata_batch(file_paths: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if not file_paths:
        return result
    field_args = [f"-{f}" for f in METADATA_FIELDS]
    for i in range(0, len(file_paths), 100):
        batch = file_paths[i : i + 100]
        try:
            cmd = ["exiftool", "-json", "-charset", "UTF8"] + field_args + batch
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode == 0 and r.stdout.strip():
                for entry in json.loads(r.stdout):
                    fpath = entry.get("SourceFile", "")
                    tags: set[str] = set()
                    for field in METADATA_FIELDS:
                        val = entry.get(field, "")
                        items = val if isinstance(val, list) else [val]
                        for v in items:
                            if v:
                                tags.update(
                                    t.strip().lower()
                                    for t in re.split(r"[,;/|]", str(v))
                                    if t.strip()
                                )
                    result[fpath] = sorted(tags)
        except Exception:
            pass
    return result


@st.cache_data(show_spinner="Library scan ho rahi hai…")
def scan_library(library_path: str) -> list[dict]:
    files: list[dict] = []
    video_paths: list[str] = []
    for root, _dirs, filenames in os.walk(library_path):
        for fname in filenames:
            if os.path.splitext(fname)[1].lower() in VIDEO_EXTENSIONS:
                full = os.path.join(root, fname)
                blob = re.sub(r"[_\-.]", " ", " ".join(Path(full).parts).lower())
                files.append({"name": fname, "path": full, "blob": blob, "tags": []})
                video_paths.append(full)
    if video_paths and check_exiftool():
        meta = _read_metadata_batch(video_paths)
        for f in files:
            f["tags"] = meta.get(f["path"], [])
    return files


def find_matches(files: list[dict], keywords: list[str]) -> list[dict]:
    results = []
    for f in files:
        score = 0
        matched_filename: list[str] = []
        matched_tags: list[str] = []
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in f["blob"]:
                score += 1
                matched_filename.append(kw)
            if any(kw_lower in t for t in f["tags"]):
                score += 2
                matched_tags.append(kw)
        if score > 0:
            results.append(
                {**f, "score": score,
                 "matched_filename": matched_filename,
                 "matched_tags": matched_tags}
            )
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ── Finder & Clipboard ────────────────────────────────────────────────────────
# ── Usage History (Mark as Used + Last used tracking) ──────────────────────
USAGE_HISTORY_PATH = "/Users/faizan/Documents/Script to B-rolls/usage_history.json"
RECENT_DAYS = 7  # 7 din ke andar use hui clip "recent" (red)


def load_usage_history() -> dict:
    try:
        with open(USAGE_HISTORY_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_usage_history(data: dict) -> None:
    try:
        with open(USAGE_HISTORY_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        st.error(f"Usage history save failed: {e}")


def mark_clip_used(filepath: str) -> None:
    data = load_usage_history()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if filepath in data:
        data[filepath]["last_used"] = now
        data[filepath]["used_count"] = data[filepath].get("used_count", 0) + 1
        hist = data[filepath].get("history", [])
        hist.append(now)
        data[filepath]["history"] = hist[-10:]  # keep last 10
    else:
        data[filepath] = {
            "last_used": now,
            "used_count": 1,
            "history": [now],
        }
    save_usage_history(data)


def reset_clip_usage(filepath: str) -> None:
    data = load_usage_history()
    if filepath in data:
        del data[filepath]
        save_usage_history(data)


def usage_indicator(filepath: str, history: dict) -> tuple[str, str, str]:
    """
    Returns (emoji, label, color_hex) based on usage status.
    🟢 Never used  → green
    🟡 Used but >7 days ago  → yellow
    🔴 Used recently (<7 days)  → red
    """
    info = history.get(filepath)
    if not info:
        return ("🟢", "Never used", "#21a150")

    try:
        last = datetime.strptime(info["last_used"], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return ("🟢", "Never used", "#21a150")

    delta = datetime.now() - last
    days = delta.days
    hours = delta.seconds // 3600
    count = info.get("used_count", 1)

    # Human-friendly relative time
    if days == 0 and hours == 0:
        ago = "just now"
    elif days == 0:
        ago = f"{hours}h ago"
    elif days == 1:
        ago = "yesterday"
    elif days < 30:
        ago = f"{days}d ago"
    else:
        ago = last.strftime("%d %b %Y")

    nice_date = last.strftime("%d %b %Y, %I:%M %p")
    label = f"Used {count}× · {ago} ({nice_date})"

    if days < RECENT_DAYS:
        return ("🔴", label, "#c0392b")
    else:
        return ("🟡", label, "#d4a017")


def reveal_in_finder(filepath: str) -> tuple[bool, str]:
    if not os.path.exists(filepath):
        return False, f"File not found: {filepath}"
    try:
        proc = subprocess.Popen(
            ["/usr/bin/open", "-R", filepath],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            _, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stderr = b""
        if proc.returncode not in (None, 0):
            err = stderr.decode().strip()
            subprocess.Popen(
                ["/usr/bin/open", os.path.dirname(filepath)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True, f"Folder opened (reveal failed: {err})"
        return True, "ok"
    except Exception as e:
        return False, str(e)


def mac_to_windows_path(mac_path: str, mac_prefix: str, win_prefix: str) -> str:
    """Convert /Volumes/NAS/file.mp4  ->  \\\\NAS_IP\\share\\file.mp4"""
    if not mac_prefix or not win_prefix or not mac_path.startswith(mac_prefix):
        return ""
    rel = mac_path[len(mac_prefix):]          # e.g. /Testing B-Rolls Library/file.mp4
    win_rel = rel.replace("/", "\\")           # \Testing B-Rolls Library\file.mp4
    return win_prefix.rstrip("\\") + win_rel   # \\NAS_IP\share\Testing B-Rolls Library\file.mp4


def explorer_open_js(win_path: str, key: str) -> None:
    """Windows pe File Explorer mein file reveal karne ka button (helper server chahiye)."""
    safe = win_path.replace("\\", "\\\\").replace("'", "\\'")
    encoded = urllib.parse.quote(win_path)
    st.components.v1.html(
        f"""<style>
          .expbtn{{background:#1a6b3c;color:white;border:none;border-radius:6px;
                   padding:5px 12px;font-size:13px;cursor:pointer;width:100%;
                   font-family:sans-serif;margin-top:4px;}}
          .expbtn:hover{{background:#145530;}}
          .expbtn.ok{{background:#21a150;}}
          .expbtn.err{{background:#c0392b;}}
        </style>
        <button class="expbtn" id="{key}"
          onclick="(function(){{
            var b=document.getElementById('{key}');
            b.textContent='Opening...';
            fetch('http://localhost:9731/open?path={encoded}')
              .then(function(r){{
                if(r.ok){{
                  b.textContent='✓ Opened!';b.classList.add('ok');
                  setTimeout(function(){{b.textContent='📂 Open in Explorer';b.classList.remove('ok');}},2000);
                }} else {{
                  b.textContent='❌ Error';b.classList.add('err');
                  setTimeout(function(){{b.textContent='📂 Open in Explorer';b.classList.remove('err');}},2000);
                }}
              }})
              .catch(function(){{
                b.textContent='❌ Helper nahi chala';b.classList.add('err');
                setTimeout(function(){{b.textContent='📂 Open in Explorer';b.classList.remove('err');}},3000);
              }});
          }})()">📂 Open in Explorer</button>""",
        height=42,
    )


def clipboard_js(text: str, label: str, key: str) -> None:
    safe = text.replace("\\", "\\\\").replace("`", "\\`").replace("'", "\\'")
    st.components.v1.html(
        f"""<style>
          .cpbtn{{background:#0068c9;color:white;border:none;border-radius:6px;
                  padding:5px 12px;font-size:13px;cursor:pointer;width:100%;
                  font-family:sans-serif;margin-top:4px;}}
          .cpbtn:hover{{background:#0052a3;}}
          .cpbtn.done{{background:#21a150;}}
        </style>
        <button class="cpbtn" id="{key}"
          onclick="navigator.clipboard.writeText('{safe}').then(function(){{
            var b=document.getElementById('{key}');
            b.textContent='✓ Copied!';b.classList.add('done');
            setTimeout(function(){{b.textContent='{label}';b.classList.remove('done');}},2000);
          }});">{label}</button>""",
        height=42,
    )


# ── Prompt Builder ────────────────────────────────────────────────────────────
def build_clipdata_prompt(s: dict, transcript: str) -> str:
    """
    Pass 1 prompt — sirf CLIP_DATA + TIMING VERIFICATION generate karta hai.
    Focused, short output — long videos (10-15 min) bhi reliably handle karta hai.
    """
    main_sec  = int(s['dmain']) * 60 + int(s['dmainsec'])
    intro_sec = int(s['dintro'])
    outro_sec = int(s['doutro'])
    total_sec = main_sec + intro_sec + outro_sec

    def _mmss(sec): return f"{sec // 60}:{sec % 60:02d}"

    has_intro = intro_sec > 0
    has_outro = outro_sec > 0

    # Post-op months — Full Journey ke liye monthly sections banane ke liye
    postop_match = re.search(r"\d+", str(s.get("postop", "")))
    postop_months = int(postop_match.group()) if postop_match else 0

    vtype = s['vtype']
    parts = []
    main_sections: list[str] = []  # equal-length sections for duration split

    if has_intro: parts.append("INTRO (highlights montage)")

    if "Pre + post" in vtype:
        # Surgery day is part of post-surgery — not a separate section
        main_sections = ["PRE-SURGERY experience", "POST-SURGERY (surgery day + recovery + results)"]
    elif "Result" in vtype or "testimonial" in vtype:
        main_sections = ["background", "why QHT", "result reveal"]
    else:  # Full journey
        # Surgery day is absorbed into post-surgery section
        main_sections = ["PRE-SURGERY experience", "POST-SURGERY (surgery day + initial recovery)"]
        if postop_months >= 1:
            for m in range(1, postop_months + 1):
                main_sections.append(f"MONTH {m} progress")
        main_sections.append("FINAL RESULT / current state")

    parts += main_sections
    if has_outro: parts.append("OUTRO")
    order = " → ".join(parts)

    # Equal duration split across main sections
    n_main = len(main_sections)
    per_section = main_sec // n_main if n_main else main_sec
    leftover = main_sec - (per_section * n_main)  # extra sec → last section gets it
    section_budget_lines = []
    for i, sec_name in enumerate(main_sections):
        sec_dur = per_section + (leftover if i == n_main - 1 else 0)
        section_budget_lines.append(f"  - {sec_name}: {sec_dur} sec ({_mmss(sec_dur)})")
    section_budget = "\n".join(section_budget_lines)

    return (
        f"You are a senior video editor building a STORY-DRIVEN clip timeline for QHT Clinic. "
        f"Your goal is NOT just to hit a duration target — it is to tell a compelling story "
        f"using the patient's own words, cut at natural speech boundaries.\n\n"

        f"=== STEP 1: ANALYZE THE TRANSCRIPT (do this silently, don't output) ===\n"
        f"Before writing any CLIP_DATA, read the ENTIRE transcript and identify:\n"
        f"  a) The patient's emotional journey arc (problem → struggle → decision → action → resolution)\n"
        f"  b) Key story beats: when does each new thought/emotion begin and end?\n"
        f"  c) Strongest soundbites — lines that carry emotional weight, humor, or vulnerability\n"
        f"  d) Natural pause points — sentence endings, breath breaks, topic changes\n"
        f"  e) The 'golden' lines that should NEVER be cut mid-thought\n\n"

        f"=== STEP 2: BUILD A NARRATIVE STRUCTURE ===\n"
        f"The MAIN section must flow like a story, not a collection of random clips:\n"
        f"  - Opening: establish the 'before' state (what was wrong, how did they feel)\n"
        f"  - Rising action: the turning point (why they decided, research, fears)\n"
        f"  - Middle: the experience (consultation, surgery day, trust-building)\n"
        f"  - Climax: the transformation (first glimpse of results, emotional moment)\n"
        f"  - Resolution: the new confident self, advice to others\n"
        f"Each clip must advance the story. If a clip doesn't move the narrative forward, skip it.\n\n"

        f"=== STEP 3: CUT CLIPS AT NATURAL BOUNDARIES (CRITICAL) ===\n"
        f"This is the most important rule. Bad cuts ruin the edit:\n"
        f"  - NEVER cut mid-sentence or mid-thought. Wait for the natural period/pause.\n"
        f"  - The clip IN point should start where a new thought/sentence begins.\n"
        f"  - The clip OUT point should land right after the last word of a complete thought, "
        f"    with only ~0.2-0.3 sec of breath. Do NOT let the clip run long into silence.\n"
        f"  - If the transcript has timestamps, use them as reference for boundaries.\n"
        f"  - Avoid clips that start with 'um', 'so', 'and then' UNLESS it's intentional and flows.\n"
        f"  - If two consecutive lines belong to the SAME thought with no big pause between, "
        f"    keep them as ONE continuous clip.\n"
        f"  - Prefer slightly longer clips with clean boundaries over short clips with ugly cuts.\n\n"

        f"=== PAUSE REMOVAL (CRITICAL — tight pacing) ===\n"
        f"The patient speaks with natural pauses between thoughts. Long pauses kill video pacing.\n"
        f"STRICT PAUSE RULES:\n"
        f"  - If there is a pause / silence / 'um...' / thinking gap of 1.5 seconds or more "
        f"    INSIDE a thought, SPLIT the clip at the pause — make it two separate CLIP_DATA lines, "
        f"    skipping over the silence entirely.\n"
        f"  - If there is a pause of 1.5+ sec at the END of a clip, cut the OUT point BEFORE "
        f"    the pause starts. Do not let silence bleed into the clip's tail.\n"
        f"  - If there is a pause of 1.5+ sec at the START of a thought, cut the IN point AFTER "
        f"    the pause — start the clip right when the actual word begins.\n"
        f"  - Use the transcript's timestamps to detect pauses: if the gap between one line's "
        f"    end timestamp and the next line's start timestamp is ≥ 1.5 sec, that IS a pause. "
        f"    Cut there.\n"
        f"  - Short natural beats (<1 sec) are fine — keep them for rhythm.\n"
        f"  - Aim for a TIGHT, punchy pace. No dead air inside any clip.\n"
        f"  - When in doubt, make the clip SHORTER, not longer. Remove silence aggressively.\n\n"

        f"=== VIDEO TYPE ===\n{vtype}\n\n"

        f"=== TIMELINE ORDER (strict) ===\n{order}\n"
        f"Never mix pre-surgery and post-surgery clips together. Pre FIRST, post AFTER.\n\n"

        f"=== DURATION TARGETS (HARD) ===\n"
        + (f"Intro: {intro_sec} sec\n" if has_intro else "Intro: DISABLED — do NOT create an intro section.\n")
        + f"Main:  {main_sec} sec ({_mmss(main_sec)}) — split across {n_main} sub-sections below:\n"
        + section_budget + "\n"
        + (f"Outro: {outro_sec} sec\n" if has_outro else "Outro: DISABLED — do NOT create an outro section.\n")
        + f"TOTAL: {total_sec} sec ({_mmss(total_sec)})\n"
        f"\nEVERY main sub-section must have approximately equal duration as shown above. "
        f"Do NOT let pre-surgery or post-surgery dominate. Each section gets its fair share.\n\n"

        f"=== CLIP LENGTH GUIDANCE ===\n"
        f"- MAIN section: aim for 5-12 sec per clip (longer is OK if the soundbite is strong).\n"
        f"  Do NOT artificially chop good soundbites into small pieces.\n"
        f"  Story beats deserve breathing room — let complete thoughts land.\n"
        + (f"- INTRO (highlights montage): 1-3 sec per clip, fast-cut, only the punchiest fragments.\n"
           if has_intro else "")
        + (f"- OUTRO: 2-5 sec per clip, conclusive tone.\n" if has_outro else "")
        + f"- DO NOT stop early. Keep adding story moments until TOTAL equals exactly {total_sec} sec.\n\n"

        f"=== UNIQUENESS RULES ===\n"
        f"- Every clip line in MAIN must be unique (different filename OR different in/out range).\n"
        f"- NEVER output the same exact filename + in/out range twice in main.\n"
        f"- If source file repeats, in/out range must be completely different (new story beat).\n\n"

        f"=== OUTPUT FORMAT ===\n"
        f"OUTPUT ONLY the CLIP_DATA block and TIMING VERIFICATION. NO explanations.\n\n"
        f"List CLIP_DATA lines in timeline order:\n"
        f"CLIP_DATA: [FILENAME.MP4] [mm:ss]-[mm:ss]\n\n"
        f"Mark section breaks with comment lines. Sections to include (in order):\n"
        + (f"# INTRO\nCLIP_DATA: ...\n" if has_intro else "")
        + "".join(f"# {sec.upper()}\nCLIP_DATA: ...\n" for sec in main_sections)
        + (f"# OUTRO\nCLIP_DATA: ...\n" if has_outro else "")
        + "\n"

        f"After all CLIP_DATA, print TIMING VERIFICATION (one line per sub-section):\n"
        f"```\n"
        f"TIMING VERIFICATION\n"
        + (f"Intro: <sum> sec (target {intro_sec}) ✓/✗\n" if has_intro else "")
        + "".join(
            f"{sec}: <sum> sec (target ~{per_section + (leftover if i == n_main-1 else 0)}) ✓/✗\n"
            for i, sec in enumerate(main_sections)
        )
        + f"Main TOTAL: <sum> sec (target {main_sec}) ✓/✗\n"
        + (f"Outro: <sum> sec (target {outro_sec}) ✓/✗\n" if has_outro else "")
        + f"GRAND TOTAL: <sum> sec (target {total_sec}) ✓/✗\n"
        f"Clip count: <n> unique clips\n"
        f"```\n\n"

        f"If TOTAL does not exactly equal {total_sec}, redistribute clip in/out points "
        f"BEFORE outputting. Never output a mismatch. When redistributing, extend or trim "
        f"clip boundaries to the NEAREST natural speech boundary — never force arbitrary cuts.\n\n"

        f"=== TRANSCRIPT ===\n{transcript}"
    )


def build_prompt(s: dict, transcript: str, clip_data: str = "") -> str:
    # Total target duration in seconds
    main_sec  = int(s['dmain']) * 60 + int(s['dmainsec'])
    intro_sec = int(s['dintro'])
    outro_sec = int(s['doutro'])
    total_sec = main_sec + intro_sec + outro_sec

    def _mmss(sec: int) -> str:
        return f"{sec // 60}:{sec % 60:02d}"

    has_intro = intro_sec > 0
    has_outro = outro_sec > 0
    intro_note = "" if has_intro else "\nINTRO is DISABLED — do NOT create an intro section."
    outro_note = "" if has_outro else "\nOUTRO is DISABLED — do NOT create an outro section."

    # Video type → narrative order
    vtype = s['vtype']
    if "Pre + post" in vtype:
        order_rules = (
            "STRICT NARRATIVE ORDER for 'Pre + Post Combined' video:\n"
            "The main section has exactly TWO equal halves: PRE-SURGERY and POST-SURGERY.\n"
            + ("  1. INTRO (hook) — cinematic highlights montage from the STRONGEST moments.\n"
               if has_intro else "")
            + "  2. PRE-SURGERY SECTION — hair loss journey, problems faced, emotional struggles, "
              "social impact, decision to get treatment, consultation, reason for choosing QHT.\n"
              "  3. POST-SURGERY SECTION — this INCLUDES surgery day (clinic arrival, procedure, "
              "doctor interaction), recovery, early days, growth timeline, results, confidence boost, "
              "final transformation reveal. Surgery day is NOT a separate section — it's part of post.\n"
            + ("  4. OUTRO — call to action, QHT branding, contact.\n" if has_outro else "")
            + "NEVER mix pre-surgery and post-surgery clips. Pre FIRST, post AFTER (surgery day "
              "belongs in the post section). Pre and post should get EQUAL duration."
            + intro_note + outro_note
        )
    elif "Result" in vtype or "testimonial" in vtype:
        order_rules = (
            "STRICT NARRATIVE ORDER for 'Result / Testimonial' video:\n"
            + ("  1. INTRO — hook with the BEST transformation reveal moment (before/after tease).\n"
               if has_intro else "")
            + "  2. Patient background (brief) — who they are, hair loss stage before surgery.\n"
              "  3. Why QHT — decision, trust, consultation highlights.\n"
              "  4. Result reveal — current look, growth, confidence, happiness.\n"
            + ("  5. Recommendation + CTA (OUTRO).\n" if has_outro else "")
            + intro_note + outro_note
        )
    else:
        order_rules = (
            "STRICT NARRATIVE ORDER for 'Full Journey' video:\n"
            "All sub-sections get EQUAL duration. Surgery day is NOT separate — "
            "it's folded into the post-surgery section.\n"
            + ("  1. INTRO hook — cinematic highlights montage from strongest moments.\n"
               if has_intro else "")
            + "  2. PRE-SURGERY — problem, research, decision, consultation.\n"
              "  3. POST-SURGERY — surgery day (arrival, procedure, doctor) + initial recovery "
              "(day 1, week 1). Surgery is part of this section, NOT separate.\n"
              "  4. MONTHLY PROGRESS — one sub-section per post-op month (month 1, month 2, etc.).\n"
              "  5. FINAL RESULT — current state, confidence, testimonial.\n"
            + ("  6. OUTRO + CTA.\n" if has_outro else "")
            + intro_note + outro_note
        )

    epd_note = ""
    if s.get("epidemic_sound") and s.get("moods"):
        epd_note = (
            f"\n\nMUSIC (Epidemic Sound):\n"
            f"- 3 intro tracks for the hook montage\n"
            f"- 3 testimonial background tracks\n"
            f"- 1 result reveal track\n"
            f"- Include BPM + suggested timestamps\n"
            f"- Mood: {', '.join(s['moods'])}"
        )

    # CLIP_DATA is ALWAYS required — edl download ke liye essential
    cd_note = (
        "\n\nCLIP_DATA OUTPUT — MANDATORY, OUTPUT THIS FIRST (before anything else):\n"
        "Start your entire response with a CLIP_DATA block. Do NOT output the edit guide, "
        "B-roll map, or any other section BEFORE the CLIP_DATA block.\n\n"
        "Format (one line per clip):\n"
        "CLIP_DATA: [FILENAME.MP4] [mm:ss]-[mm:ss]\n\n"
        "RULES:\n"
        "- Order must match timeline order (intro first, then pre, surgery, post, outro).\n"
        "- mm:ss are the IN and OUT points INSIDE the source clip (not timeline position).\n"
        "- Duration of each clip = (out - in) in seconds.\n"
        f"- The TOTAL duration of all CLIP_DATA lines MUST equal exactly {total_sec} seconds "
        f"({_mmss(total_sec)}). This is NON-NEGOTIABLE.\n"
        "- After CLIP_DATA block, print the TIMING VERIFICATION block.\n"
        "- ONLY AFTER CLIP_DATA + TIMING VERIFICATION, continue with the detailed "
        "edit guide, B-roll map, priority table, and other sections.\n"
    )

    return (
        f"You are a professional video editor for QHT Clinic (hair transplant).\n"
        f"Produce a complete edit plan in {s['lang']} from the patient testimonial transcript below.\n\n"

        f"=== PATIENT ===\n"
        f"Name: {s['pname']} | City: {s['pcity']}\n"
        f"Grafts: {s['grafts']} | Surgery: {s['sdate']} | Post-op: {s['postop']} months\n\n"

        f"=== VIDEO ===\n"
        f"Type:     {vtype}\n"
        f"Software: {s['sw']}\n"
        f"Language: {s['lang']}\n\n"

        f"=== DURATION (STRICT — MUST BE EXACT) ===\n"
        + (f"Intro:  {intro_sec} sec\n" if has_intro else "Intro:  DISABLED — skip this section entirely.\n")
        + f"Main:   {main_sec} sec ({_mmss(main_sec)})\n"
        + (f"Outro:  {outro_sec} sec\n" if has_outro else "Outro:  DISABLED — skip this section entirely.\n")
        + f"TOTAL:  {total_sec} sec ({_mmss(total_sec)})\n\n"

        f"TIMING RULES — THESE ARE HARD CONSTRAINTS:\n"
        + (f"- The intro section MUST be exactly {intro_sec} seconds.\n" if has_intro else "")
        + f"- The main section MUST be exactly {main_sec} seconds ({_mmss(main_sec)}).\n"
        + (f"- The outro section MUST be exactly {outro_sec} seconds.\n" if has_outro else "")
        + f"- Total video MUST be exactly {total_sec} seconds ({_mmss(total_sec)}).\n"
        f"- For every section and every clip, include a running timestamp.\n"
        f"- At the end of each section, verify and print the section's total duration.\n\n"

        f"CLIP UNIQUENESS RULES (IMPORTANT):\n"
        f"- In the MAIN section, every clip (filename + in/out timestamp range) MUST be unique. "
        f"NO clip should repeat inside the main section.\n"
        f"- If the same source file is used more than once in the main, it MUST be a DIFFERENT "
        f"in/out range — never the exact same segment twice.\n"
        f"- The intro montage MAY reuse highlight moments from clips that also appear later, "
        f"but even there, avoid using the exact same in/out range more than once.\n"
        f"- If you run out of unique content before hitting the main duration, pick OTHER "
        f"unused segments from the transcript instead of repeating.\n\n"

        f"CLIP COUNT GUIDANCE (CRITICAL FOR DURATION):\n"
        f"- Average clip length should be 4-8 seconds for talking head + B-roll mix.\n"
        f"- For the MAIN section of {main_sec} sec, you need approximately "
        f"{max(main_sec // 7, 10)} to {max(main_sec // 4, 15)} clips.\n"
        + (f"- For the INTRO of {intro_sec} sec (fast-cut montage), use 1-3 sec clips → "
           f"approximately {max(intro_sec // 2, 5)} to {max(intro_sec, 8)} clips.\n"
           if has_intro else "")
        + (f"- For the OUTRO of {outro_sec} sec, use 2-5 sec clips → approximately "
           f"{max(outro_sec // 4, 3)} to {max(outro_sec // 2, 5)} clips.\n"
           if has_outro else "")
        + f"- DO NOT stop early. If your CLIP_DATA total is less than {total_sec} seconds, "
        f"ADD MORE CLIPS from the transcript until the sum reaches exactly {total_sec} sec.\n"
        f"- It is better to output MORE clips than to fall short of the duration target.\n\n"

        f"=== NARRATIVE STRUCTURE ===\n"
        f"{order_rules}\n\n"

        + (
            f"=== INTRO SPECIFICATION (IMPORTANT) ===\n"
            f"The intro ({intro_sec} sec) is NOT a slow patient introduction.\n"
            f"It is a cinematic HIGHLIGHTS MONTAGE built from the most powerful moments of the transcript:\n"
            f"- Strongest emotional soundbites\n"
            f"- Best transformation visuals (if post footage exists)\n"
            f"- Most quotable lines\n"
            f"- Fast-cut, 1-3 second clips\n"
            f"- Ends with the patient's name + city card OR a teaser line\n"
            f"Pick these highlight moments from ACROSS the full transcript.\n\n"
            if has_intro else ""
        ) +

        f"=== OUTPUT ORDER (STRICT) ===\n"
        f"1. CLIP_DATA block (exactly the lines provided below, unchanged)\n"
        f"2. TIMING VERIFICATION block (copy from below)\n"
        f"3. Then the detailed sections: {', '.join(s['outputs'])}\n\n"
        f"For each section include: timestamp range, dialogue/VO, visual/B-roll direction, "
        f"transition, music cue, and any on-screen text.{epd_note}\n\n"

        f"=== USE THESE EXACT CLIPS (from Pass 1) ===\n"
        f"The CLIP_DATA below has already been validated and timed to match the target duration. "
        f"Build your detailed edit guide AROUND these exact clips. Do NOT add new clips, do NOT "
        f"remove any, do NOT change their order or in/out points. Reference them by filename + "
        f"in/out in your section breakdowns.\n\n"
        f"{clip_data if clip_data else '[CLIP_DATA will be provided in Pass 1]'}\n\n"

        f"=== TRANSCRIPT ===\n{transcript}"
    )


# ── EDL Helpers ───────────────────────────────────────────────────────────────
def _to_tc(total_sec: int, frame: int) -> str:
    h = total_sec // 3600
    rem = total_sec % 3600
    return f"{h:02d}:{rem // 60:02d}:{rem % 60:02d}:{frame:02d}"


def build_edl(parsed: list[dict], fps: int, title: str) -> str:
    """
    CMX3600-compliant EDL.
    Columns (fixed-width):
      EditNum(3)  Reel(8)  Track(4)  Trans(4)  SrcIn  SrcOut  RecIn  RecOut
    """
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    tl = 0  # timeline cursor in frames

    for i, c in enumerate(parsed):
        num = f"{i + 1:03d}"
        # Reel name: 8 chars max, no extension, padded
        reel = re.sub(r"\.[a-z0-9]+$", "", c["name"], flags=re.IGNORECASE)
        reel = reel[:8].ljust(8)

        in_f  = c["in"]  * fps
        out_f = c["out"] * fps
        dur   = out_f - in_f
        tl_out = tl + dur

        si = _to_tc(c["in"], 0)
        so = _to_tc(c["out"], 0)
        ri = _to_tc(tl // fps, tl % fps)
        ro = _to_tc(tl_out // fps, tl_out % fps)

        # V track
        lines.append(f"{num}  {reel} V     C        {si} {so} {ri} {ro}")
        lines.append(f"* FROM CLIP NAME: {c['name']}")
        # AA (stereo audio) — Premiere / DaVinci dono samajhte hain
        lines.append(f"{num}  {reel} AA    C        {si} {so} {ri} {ro}")
        lines.append(f"* FROM CLIP NAME: {c['name']}")
        lines.append("")

        tl = tl_out

    return "\n".join(lines)


def parse_clip_data(text: str) -> list[dict]:
    """
    Flexible CLIP_DATA parser — bracket ho ya na ho, kaam karega.
    Examples jo match honge:
      CLIP_DATA: [C3414.MP4] [0:02]-[0:27]
      CLIP_DATA: C3414.MP4 0:02-0:27
      CLIP_DATA: [C3414.MP4] 0:02 - 0:27
      C3414.MP4  0:02-0:27
    """
    clips = []
    # Filename + 2 timestamps (dono brackets optional)
    pattern = re.compile(
        r"\[?([A-Za-z0-9_\-]+\.(?:mp4|mov|avi|mkv|mxf|m4v))\]?"  # filename
        r"[\s\]\[]*"
        r"\[?(\d{1,2}):(\d{2})\]?"                                # in time
        r"\s*[-–—to]+\s*"
        r"\[?(\d{1,2}):(\d{2})\]?",                               # out time
        re.IGNORECASE,
    )
    for line in text.splitlines():
        m = pattern.search(line)
        if m:
            clips.append({
                "name": m.group(1).strip(),
                "in":  int(m.group(2)) * 60 + int(m.group(3)),
                "out": int(m.group(4)) * 60 + int(m.group(5)),
            })
    return clips


# ══════════════════════════════════════════════════════════════════════════════
#                                SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("⚙️ Settings")

    st.divider()
    st.subheader("🧑 Patient Info")
    _c1, _c2 = st.columns(2)
    pname = _c1.text_input("Name", placeholder="Paras Agarwal")
    pcity = _c2.text_input("City", placeholder="Delhi")
    _c3, _c4, _c5 = st.columns(3)
    pgrafts = _c3.text_input("Grafts", placeholder="3200")
    psdate  = _c4.text_input("Surgery", placeholder="Jan 2025")
    pmopo   = _c5.text_input("Post-op", placeholder="6 mo")

    st.divider()
    st.subheader("🎥 Video Settings")
    vtype = st.selectbox("Video Type", [
        "Pre + post combined", "Result / testimonial", "Full journey",
    ])
    _c6, _c7 = st.columns(2)
    dmain    = _c6.number_input("Main (min)", 1, 60, 8)
    dmainsec = _c7.number_input("Main (sec)", 0, 59, 0)

    intro_on = st.checkbox("Include Intro", value=True)
    if intro_on:
        dintro = st.number_input("Intro (sec)", 0, 120, 30)
    else:
        dintro = 0
        st.caption("Intro disabled")

    outro_on = st.checkbox("Include Outro", value=True)
    if outro_on:
        doutro = st.number_input("Outro (sec)", 0, 120, 20)
    else:
        doutro = 0
        st.caption("Outro disabled")

    _total = dmain * 60 + dmainsec + dintro + doutro
    st.caption(f"⏱ Total: {_total // 60} min {_total % 60} sec")

    lang = st.radio("Language", ["Hinglish", "Hindi", "English"], horizontal=True)
    sw   = st.selectbox("Software", ["Premiere Pro", "DaVinci Resolve", "Final Cut Pro"])

    st.divider()
    st.subheader("📋 Output Sections")
    _guide    = st.checkbox("Edit guide",      value=True)
    _brollmap = st.checkbox("B-roll map",      value=True)
    _priority = st.checkbox("Priority table",  value=True)
    _tips     = st.checkbox("Software tips",   value=True)
    _seq      = st.checkbox("Edit sequence",   value=True)
    _epd      = st.checkbox("Epidemic Sound",  value=False)
    _moods: list[str] = []
    if _epd:
        _moods = st.multiselect(
            "Music moods",
            ["Emotional", "Cinematic", "Motivational", "Calm", "Upbeat", "Melancholic"],
            default=["Emotional"],
        )
    _cd = st.checkbox("CLIP_DATA for EDL", value=True)

    _outputs: list[str] = (
        (["Edit guide"]     if _guide    else []) +
        (["B-roll map"]     if _brollmap else []) +
        (["Priority table"] if _priority else []) +
        (["Software tips"]  if _tips     else []) +
        (["Edit sequence"]  if _seq      else []) +
        (["Epidemic Sound"] if _epd      else [])
    )

    st.divider()
    st.subheader("📁 B-Roll Library")
    library_path = st.text_input("Mac Library Path", value=DEFAULT_LIBRARY)
    max_results  = st.slider("Max B-roll results", 1, 30, 10)

    st.caption("Windows Network Path Settings")
    nas_mac_prefix = st.text_input(
        "Mac NAS mount prefix",
        value=DEFAULT_MAC_PREFIX,
        help="Mac pe NAS kahan mount hai, e.g. /Volumes/PHOTOGRAPHY",
    )
    nas_win_prefix = st.text_input(
        "Windows UNC prefix",
        value=DEFAULT_WIN_PREFIX,
        help=r"Windows pe NAS ka UNC path, e.g. \\192.168.1.100\PHOTOGRAPHY",
    )

    if st.button("🔄 Rescan Library", use_container_width=True):
        scan_library.clear()
        st.session_state.broll_results = []
        st.session_state.broll_keywords = []
        st.success("Cache cleared — next generate pe rescan hoga")

    st.divider()
    try:
        import spacy
        spacy.load("en_core_web_sm")
        st.success("spaCy ✓")
    except Exception:
        st.warning("spaCy not found — basic tokenizer use hoga")
    if check_exiftool():
        st.success("ExifTool ✓")
    else:
        st.warning("ExifTool not found\n`brew install exiftool`")


# ══════════════════════════════════════════════════════════════════════════════
#                                MAIN AREA
# ══════════════════════════════════════════════════════════════════════════════
st.title("🎬 QHT Video Tools")

tab1, tab2 = st.tabs(["⚡ Script Generator + B-Roll", "🔍 Sirf B-Roll Finder"])

# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — B-Roll Finder Only  (pehle define karo taaki variables available hon)
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("🔍 B-Roll Finder")
    st.caption("Koi bhi text paste karo — keywords khud nikal ke B-rolls dhundhe jayenge.")

    solo_text = st.text_area(
        "Text / Keywords",
        height=160,
        placeholder=(
            "Yahan kuch bhi paste karo:\n"
            "• Kuch keywords  (e.g. hair transplant, before after, surgery)\n"
            "• Script ka koi hissa\n"
            "• Scene description"
        ),
        label_visibility="collapsed",
        key="solo_input",
    )

    solo_clicked = st.button(
        "🔍 B-Rolls Dhundho",
        type="primary",
        use_container_width=True,
        key="solo_btn",
    )

    if solo_clicked:
        if not solo_text.strip():
            st.warning("Kuch text ya keywords daalo pehle!")
        elif not os.path.isdir(library_path):
            st.error(f"Library path nahi mili: `{library_path}`")
        else:
            with st.spinner("Keywords nikal rahe hain…"):
                solo_kws = extract_keywords_spacy(solo_text)
            if not solo_kws:
                st.warning("Koi keyword nahi mila.")
            else:
                with st.spinner("B-rolls dhundh rahe hain…"):
                    solo_files = scan_library(library_path)
                    solo_matches = find_matches(solo_files, solo_kws)[:max_results]
                st.session_state.solo_keywords    = solo_kws
                st.session_state.solo_results     = solo_matches
                st.session_state.solo_open_status = {}

    # Keywords
    if st.session_state.solo_keywords:
        with st.expander(f"🔑 {len(st.session_state.solo_keywords)} keywords", expanded=False):
            st.write(" ".join(f"`{k}`" for k in st.session_state.solo_keywords))

    # Results
    if st.session_state.solo_results:
        st.success(f"**{len(st.session_state.solo_results)} B-roll clips mili!**")
        usage_hist_solo = load_usage_history()

        for idx, m in enumerate(st.session_state.solo_results):
            emoji, ulabel, ucolor = usage_indicator(m["path"], usage_hist_solo)

            with st.container(border=True):
                # Usage badge — top
                st.markdown(
                    f"<span style='background:{ucolor};color:white;padding:3px 10px;"
                    f"border-radius:12px;font-size:11px;font-family:monospace'>"
                    f"{emoji} {ulabel}</span>",
                    unsafe_allow_html=True,
                )

                ci, ca = st.columns([3, 1])

                with ci:
                    st.markdown(f"**{m['name']}**")
                    parts = [f"Score: **{m['score']}**"]
                    if m["matched_filename"]:
                        parts.append("Name: " + " ".join(f"`{k}`" for k in m["matched_filename"]))
                    if m["matched_tags"]:
                        parts.append("🏷️ " + " ".join(f"`{k}`" for k in m["matched_tags"]))
                    st.caption("  ·  ".join(parts))

                with ca:
                    if st.button("📂 Reveal (Mac)", key=f"solo_finder_{idx}", use_container_width=True):
                        ok, msg = reveal_in_finder(m["path"])
                        st.session_state.solo_open_status[idx] = (ok, msg)

                    if st.button("✓ Mark as Used", key=f"solo_used_{idx}", use_container_width=True):
                        mark_clip_used(m["path"])
                        st.rerun()

                if idx in st.session_state.solo_open_status:
                    ok, msg = st.session_state.solo_open_status[idx]
                    if ok:
                        st.success("✓ Revealed" if msg == "ok" else msg)
                    else:
                        st.error(f"Error: {msg}")

                win_path = mac_to_windows_path(m["path"], nas_mac_prefix, nas_win_prefix)
                if win_path:
                    explorer_open_js(win_path, key=f"solo_exp_{idx}")
                    st.code(win_path, language=None)

    elif st.session_state.solo_keywords and not solo_clicked:
        st.info("In keywords ke liye koi B-roll nahi mila.")

# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — Script Generator + B-Roll
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.caption("Transcript paste karo → Generate dabao → Script stream hogi + B-rolls automatic milenge!")

    transcript = st.text_area(
        "Transcript",
        height=200,
        placeholder=(
            "Transcript yahan paste karo...\n\n"
            "Format:\nC3413.MP4\n0:02 dialogue text..."
        ),
        label_visibility="collapsed",
    )

    gen_clicked = st.button(
        "⚡ Generate Script + Find B-Rolls",
        type="primary",
        use_container_width=True,
    )

    # Load API key from secrets (server-side only)
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
    except Exception:
        api_key = ""
        st.error("API key server pe set nahi hai. `.streamlit/secrets.toml` mein daalo.")

    # Validate
    if gen_clicked:
        if not transcript.strip():
            st.warning("Transcript paste karo pehle!")
            gen_clicked = False
        elif not api_key:
            st.error("API key configure nahi hai — server admin se baat karo.")
            gen_clicked = False

    # ── Output Area ──────────────────────────────────────────────────────────
    if gen_clicked or st.session_state.generated_script:
        st.divider()
        left_col, right_col = st.columns([1.3, 1], gap="large")

        full_script = st.session_state.generated_script

        # ─── LEFT: Generated Script ──────────────────────────────────────────
        with left_col:
            st.subheader("📄 Generated Script")

            if gen_clicked:
                settings = {
                    "pname":          pname   or "Not specified",
                    "pcity":          pcity   or "Not specified",
                    "grafts":         pgrafts or "Not specified",
                    "sdate":          psdate  or "Not specified",
                    "postop":         pmopo   or "Not specified",
                    "vtype":          vtype,
                    "dmain":          dmain,
                    "dmainsec":       dmainsec,
                    "dintro":         dintro,
                    "doutro":         doutro,
                    "lang":           lang,
                    "sw":             sw,
                    "outputs":        _outputs,
                    "epidemic_sound": _epd,
                    "moods":          _moods,
                    "clip_data":      _cd,
                }
                try:
                    from openai import OpenAI
                    client = OpenAI(api_key=api_key, timeout=300.0, max_retries=2)

                    # ════════════════════════════════════════════════════════════
                    # PASS 1 — Sirf CLIP_DATA + TIMING VERIFICATION
                    # Short, focused output — duration strictly match hogi
                    # ════════════════════════════════════════════════════════════
                    st.info("📋 Pass 1/2 — CLIP_DATA generate ho raha hai…")
                    cd_prompt = build_clipdata_prompt(settings, transcript)

                    def _stream_pass1():
                        stream = client.chat.completions.create(
                            model="gpt-4o",
                            max_tokens=8000,
                            stream=True,
                            temperature=0.3,  # focused, less creative
                            messages=[{"role": "user", "content": cd_prompt}],
                        )
                        for chunk in stream:
                            if chunk.choices and chunk.choices[0].delta.content:
                                yield chunk.choices[0].delta.content

                    clip_data_block = st.write_stream(_stream_pass1())

                    # ════════════════════════════════════════════════════════════
                    # PASS 2 — Detailed edit guide using Pass 1 clips
                    # ════════════════════════════════════════════════════════════
                    st.info("🎬 Pass 2/2 — Detailed edit guide generate ho raha hai…")
                    full_prompt = build_prompt(settings, transcript, clip_data=clip_data_block)

                    def _stream_pass2():
                        stream = client.chat.completions.create(
                            model="gpt-4o",
                            max_tokens=16000,
                            stream=True,
                            messages=[{"role": "user", "content": full_prompt}],
                        )
                        for chunk in stream:
                            if chunk.choices and chunk.choices[0].delta.content:
                                yield chunk.choices[0].delta.content

                    edit_guide = st.write_stream(_stream_pass2())

                    # Combine both for storage
                    full_script = clip_data_block + "\n\n---\n\n" + edit_guide
                    st.session_state.generated_script = full_script
                    st.session_state.just_generated = True

                    # Extract CLIP_DATA from Pass 1 directly (most reliable)
                    cd_lines = re.findall(r"CLIP_DATA:[^\n]+", clip_data_block)
                    if not cd_lines:
                        cd_lines = re.findall(
                            r"[A-Za-z0-9_\-]+\.(?:mp4|mov|avi|mkv)[^\n]*?\d{1,2}:\d{2}[^\n]*?\d{1,2}:\d{2}",
                            clip_data_block, re.IGNORECASE,
                        )
                    if cd_lines:
                        st.session_state.clip_data_lines = "\n".join(cd_lines)

                except Exception as e:
                    st.error(f"API Error: {e}")
                    full_script = ""
            else:
                st.markdown(full_script)

            if full_script:
                if st.button("📋 Script Copy karo", use_container_width=True):
                    st.code(full_script, language=None)

        # ─── RIGHT: B-Roll Matches ────────────────────────────────────────────
        with right_col:
            st.subheader("🎬 B-Roll Matches")

            if gen_clicked and st.session_state.just_generated and full_script:
                st.session_state.just_generated = False
                if os.path.isdir(library_path):
                    with st.spinner("Keywords extract + B-rolls dhundh rahe hain…"):
                        kws = extract_keywords_spacy(full_script)
                        files = scan_library(library_path)
                        matches = find_matches(files, kws)[:max_results]
                    st.session_state.broll_keywords = kws
                    st.session_state.broll_results  = matches
                    st.session_state.open_status    = {}
                else:
                    st.warning(f"Library path nahi mili:\n`{library_path}`")

            if st.session_state.broll_keywords:
                with st.expander(
                    f"🔑 {len(st.session_state.broll_keywords)} keywords extracted",
                    expanded=False,
                ):
                    st.write(" ".join(f"`{k}`" for k in st.session_state.broll_keywords))

            results = st.session_state.broll_results
            if results:
                st.success(f"**{len(results)} B-roll clips mili!**")
                usage_hist_t1 = load_usage_history()
                for idx, m in enumerate(results):
                    emoji, ulabel, ucolor = usage_indicator(m["path"], usage_hist_t1)
                    with st.container(border=True):
                        st.markdown(
                            f"<span style='background:{ucolor};color:white;padding:3px 10px;"
                            f"border-radius:12px;font-size:11px;font-family:monospace'>"
                            f"{emoji} {ulabel}</span>",
                            unsafe_allow_html=True,
                        )
                        ci, ca = st.columns([3, 1])
                        with ci:
                            st.markdown(f"**{m['name']}**")
                            parts = [f"Score: **{m['score']}**"]
                            if m["matched_filename"]:
                                parts.append("Name: " + " ".join(f"`{k}`" for k in m["matched_filename"]))
                            if m["matched_tags"]:
                                parts.append("🏷️ " + " ".join(f"`{k}`" for k in m["matched_tags"]))
                            st.caption("  ·  ".join(parts))
                        with ca:
                            if st.button("📂 Reveal (Mac)", key=f"finder_{idx}", use_container_width=True):
                                ok, msg = reveal_in_finder(m["path"])
                                st.session_state.open_status[idx] = (ok, msg)
                            if st.button("✓ Mark as Used", key=f"t1_used_{idx}", use_container_width=True):
                                mark_clip_used(m["path"])
                                st.rerun()
                        if idx in st.session_state.open_status:
                            ok, msg = st.session_state.open_status[idx]
                            if ok:
                                st.success("✓ Revealed" if msg == "ok" else msg)
                            else:
                                st.error(f"Error: {msg}")
                        win_path = mac_to_windows_path(m["path"], nas_mac_prefix, nas_win_prefix)
                        if win_path:
                            explorer_open_js(win_path, key=f"tab1_exp_{idx}")
                            st.code(win_path, language=None)
            elif st.session_state.generated_script and not gen_clicked:
                st.info("In keywords ke liye koi B-roll match nahi mila.")
            elif not gen_clicked:
                st.info("Generate dabao — keywords se B-rolls automatically milenge!")
            else:
                st.info("Script generate ho rahi hai…")

    # ── EDL Generator ────────────────────────────────────────────────────────
    st.divider()
    with st.expander("📼 EDL Generator", expanded=True):
        st.caption(
            "Script se CLIP_DATA auto-fill hoti hai. Agar empty ho toh manually "
            "paste karo — koi bhi format chalega (brackets optional)."
        )
        fps_val = st.radio("FPS", ["25", "24", "30"], horizontal=True, key="edl_fps")
        fps = int(fps_val)

        cd_text = st.text_area(
            "CLIP_DATA lines",
            value=st.session_state.clip_data_lines,
            height=140,
            placeholder=(
                "CLIP_DATA: [C3414.MP4] [0:02]-[0:27]\n"
                "CLIP_DATA: C3412.MP4 0:05-0:18\n"
                "C3410.MP4  1:20-1:45"
            ),
            key="edl_cd_text",
        )

        parsed_preview = parse_clip_data(cd_text) if cd_text.strip() else []
        if parsed_preview:
            st.caption(f"✓ {len(parsed_preview)} valid clips ready")
        else:
            st.caption("0 valid clips — paste ya edit karo")

        # Generate button
        if st.button(
            "⚙️ Generate EDL",
            type="primary",
            use_container_width=True,
            disabled=not parsed_preview,
            key="edl_gen_btn",
        ):
            edl_title = (pname or "QHT").replace(" ", "_")
            st.session_state.edl_content   = build_edl(parsed_preview, fps, edl_title)
            st.session_state.edl_clips     = parsed_preview
            st.session_state.edl_generated = True

        # Agar generate ho chuka hai toh download + preview dikhao
        if st.session_state.edl_generated and st.session_state.edl_content:
            edl_title = (pname or "QHT").replace(" ", "_")
            n = len(st.session_state.edl_clips)
            st.success(f"✓ EDL ready — {n} clips")

            st.download_button(
                label=f"⬇️ Download EDL ({n} clips)",
                data=st.session_state.edl_content,
                file_name=f"{edl_title}_{fps}fps.edl",
                mime="text/plain",
                use_container_width=True,
                key="edl_dl_btn",
            )

            with st.expander("🔍 Parsed clips preview", expanded=False):
                for c in st.session_state.edl_clips:
                    dur = c["out"] - c["in"]
                    st.caption(
                        f"• **{c['name']}** — "
                        f"{c['in']//60}:{c['in']%60:02d} → {c['out']//60}:{c['out']%60:02d} "
                        f"({dur}s)"
                    )

            with st.expander("📄 EDL file content", expanded=False):
                st.code(st.session_state.edl_content, language=None)
