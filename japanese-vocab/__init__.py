import sys
import os
from typing import Optional, List
import json
import urllib.request
import urllib.parse
import urllib.error

from aqt import mw
from aqt.utils import showInfo, qconnect, tooltip, askUser, getText
from aqt.qt import *
from aqt.qt import QAction
from anki.notes import Note
from anki.collection import Collection


def get_openai_key() -> Optional[str]:
    """Get OpenAI API key from add-on config."""
    config = mw.addonManager.getConfig(__name__)
    if not config:
        showInfo("No configuration found. Please set up your OpenAI API key in the add-on config.")
        return None
    
    api_key = config.get("openai_key")
    if not api_key:
        showInfo("No OpenAI API key found in config. Please add your key to the add-on configuration.")
        return None
    
    return api_key


def get_selected_notes() -> List[Note]:
    """Get currently selected notes in the browser."""
    # Try to get the browser window
    browser = None
    for window in mw.app.topLevelWidgets():
        if hasattr(window, 'selectedNotes') and window.isVisible():
            browser = window
            break
    
    if not browser:
        return []
    
    selected_nids = browser.selectedNotes()
    if not selected_nids:
        return []
    
    return [mw.col.get_note(nid) for nid in selected_nids]


def call_openai_api(api_key: str, prompt: str, max_retries: int = 3):
    """Make a JSON API call to OpenAI using urllib with retry logic."""
    url = "https://api.openai.com/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant that provides accurate Japanese language information. Always respond with valid JSON matching the requested format."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1
    }
    
    for attempt in range(max_retries):
        try:
            # Prepare the request
            json_data = json.dumps(data).encode('utf-8')
            request = urllib.request.Request(url, data=json_data, headers=headers)
            
            # Make the request
            with urllib.request.urlopen(request) as response:
                response_text = response.read().decode('utf-8')
                response_json = json.loads(response_text)
                
                # Extract the content from OpenAI response
                content = response_json["choices"][0]["message"]["content"]
                return json.loads(content)
                
        except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
            if attempt == max_retries - 1:
                raise Exception(f"Failed to get response from OpenAI: {e}")
            continue
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            continue


def generate_kanji():
    """Generate kanji from kana and English meaning for selected notes."""
    api_key = get_openai_key()
    if not api_key:
        return
    
    try:
        notes = get_selected_notes()
        
        if not notes:
            showInfo("No notes selected. Please select notes in the browser first.")
            return
        
        processed = 0
        errors = 0
        
        for note in notes:
            try:
                # Check if note has required fields
                if "Kana" not in note or "English" not in note or "Kanji" not in note:
                    print(f"Skipping note - missing required fields. Available fields: {list(note.keys())}")
                    continue
                
                kana = note["Kana"].strip()
                english = note["English"].strip()
                current_kanji = note["Kanji"].strip()
                
                # Skip if already has kanji or missing required data
                if not kana or not english or current_kanji:
                    continue
                
                # Generate kanji using OpenAI
                prompt = f"""Given the Japanese word in kana "{kana}" with the English meaning "{english}", provide the appropriate kanji spelling. If there is a standard kanji spelling for this word, provide it. If the word is typically written only in kana (like some foreign loanwords or onomatopoeia), return null for kanji. Consider common usage and standard dictionary forms.

Please respond with a JSON object in this exact format:
{{
    "kanji": "kanji_spelling_or_null",
    "explanation": "brief_explanation"
}}

If there is no appropriate kanji, use null (not a string) for the kanji field."""
                
                response = call_openai_api(api_key, prompt)
                
                if response.get("kanji"):
                    note["Kanji"] = response["kanji"]
                    note.flush()
                    processed += 1
                
            except Exception as e:
                errors += 1
                print(f"Error processing note: {e}")
                continue
        
        if processed > 0:
            tooltip(f"Generated kanji for {processed} notes.")
        else:
            showInfo("No kanji generated. Make sure you have selected notes with Kana and English fields that don't already have Kanji.")
        
        if errors > 0:
            showInfo(f"Encountered {errors} errors during processing.")
            
    except Exception as e:
        showInfo(f"Error: {str(e)}")


def generate_romaji():
    """Generate romaji from kana for selected notes."""
    api_key = get_openai_key()
    if not api_key:
        return
    
    try:
        notes = get_selected_notes()
        
        if not notes:
            showInfo("No notes selected. Please select notes in the browser first.")
            return
        
        processed = 0
        errors = 0
        
        for note in notes:
            try:
                # Check if note has required fields
                if "Kana" not in note or "Romanji" not in note:
                    print(f"Skipping note - missing required fields. Available fields: {list(note.keys())}")
                    continue
                
                kana = note["Kana"].strip()
                current_romaji = note["Romanji"].strip()
                
                # Skip if no kana or already has romaji
                if not kana or current_romaji:
                    continue
                
                # Generate romaji using OpenAI
                prompt = f"""Convert the Japanese kana "{kana}" to romaji (romanized Japanese). You are to use the following style guidelines:
                - Spell each kana character individually; do not use macrons for long vowels. For example, use "おう" turns into "ou", but "おお" turns into "oo". "えい" turns into "ei", but "ええ" turns into "ee".
                - The long dash (ー) in katakana should extend the preceding vowel sound (e.g., "コーヒー" becomes "koohii").
                - The small "っ" (sokuon) should be represented by doubling the consonant that follows it. Do not convert "cch" to "tch"; for example, "まっちゃ" becomes "maccha", not "matcha".
                - Always write the nasal ん as "n". Do not assimilate it to "m".
                - Add spaces after words and around particles. Also, if a word is a compound word, add proper spacing to break the word up roughly into morphemes, but be logical about it. For example, "かんこうきゃくはきれいです” should be "kankyou kyaku wa kirei desu".
                - Render the particle "は" as "wa", the particle "へ" as "e", and the particle "を" as "o" when they function as particles in a sentence. In other contexts, render them according to their standard pronunciations.
                - Capitalize the first letter of the output, but do not capitalize anything else.

Please respond with a JSON object in this exact format:
{{
    "romaji": "romanized_text"
}}"""
                
                response = call_openai_api(api_key, prompt)
                
                if response.get("romaji"):
                    note["Romanji"] = response["romaji"]
                    note.flush()
                    processed += 1
                
            except Exception as e:
                errors += 1
                print(f"Error processing note: {e}")
                continue
        
        if processed > 0:
            tooltip(f"Generated romaji for {processed} notes.")
        else:
            showInfo("No romaji generated. Make sure you have selected notes with Kana field that don't already have Romanji.")
        
        if errors > 0:
            showInfo(f"Encountered {errors} errors during processing.")
            
    except Exception as e:
        showInfo(f"Error: {str(e)}")

# ===========================================================================
# Card flags for the merged "Japanese" note type
#
# The Cards field holds any subset of "p w m r" (produce / write / meaning /
# read).  Anki template conditionals can only test a field for emptiness, so
# one field cannot gate four cards; Cards is expanded into four hidden gate
# fields _P/_W/_M/_R which the templates actually test.
# ===========================================================================

JAPANESE_NOTETYPE = "Japanese"
FLAG_ORDER = "pwmr"
# flag letter -> (gate field, template ord)
FLAG_SPEC = {
    "p": ("_P", 0),
    "w": ("_W", 1),
    "m": ("_M", 2),
    "r": ("_R", 3),
}
ORD_LABEL = {0: "Produce", 1: "Write", 2: "Meaning", 3: "Read"}


def normalise_flags(raw: str) -> str:
    """Canonical flag string: lower case, deduplicated, in p-w-m-r order."""
    seen = {ch for ch in (raw or "").lower() if ch in FLAG_ORDER}
    return "".join(ch for ch in FLAG_ORDER if ch in seen)


def _japanese_notes(notes: List[Note]) -> List[Note]:
    nt = mw.col.models.by_name(JAPANESE_NOTETYPE)
    if not nt:
        showInfo(f"Note type {JAPANESE_NOTETYPE!r} not found.")
        return []
    return [n for n in notes if n.mid == nt["id"]]


def _studied_cards_losing_their_flag(note: Note, flags: str):
    """Cards that have review history but whose flag letter was removed.

    Letting these through would render an empty front, and the card's
    scheduling would then be destroyed by Tools > Empty Cards.
    """
    at_risk = []
    for card in note.cards():
        letter = next((l for l, (_g, o) in FLAG_SPEC.items() if o == card.ord), None)
        if letter and letter not in flags and card.reps > 0:
            at_risk.append((letter, card))
    return at_risk


def _apply_flags(note: Note, flags: str) -> bool:
    """Write Cards + the four gate fields. Returns True if anything changed."""
    changed = False
    if note["Cards"] != flags:
        note["Cards"] = flags
        changed = True
    for letter, (gate, _ord) in FLAG_SPEC.items():
        want = "1" if letter in flags else ""
        if note[gate] != want:
            note[gate] = want
            changed = True
    return changed


def _sync(notes: List[Note], new_flags: Optional[str] = None) -> None:
    """Shared worker for both menu actions."""
    notes = _japanese_notes(notes)
    if not notes:
        showInfo(f"No {JAPANESE_NOTETYPE} notes selected. Select some in the browser first.")
        return

    # --- guard: never silently strip a flag off a card with history --------
    risky = []
    for note in notes:
        flags = normalise_flags(new_flags if new_flags is not None else note["Cards"])
        for letter, card in _studied_cards_losing_their_flag(note, flags):
            risky.append((note, letter, card))

    suspend_instead = False
    if risky:
        preview = "\n".join(
            f"  {n['English'][:40]} — {ORD_LABEL[c.ord]} card, {c.reps} reviews"
            for n, _l, c in risky[:10]
        )
        more = f"\n  ...and {len(risky) - 10} more" if len(risky) > 10 else ""
        suspend_instead = askUser(
            f"{len(risky)} card(s) have review history but their flag is being removed:\n\n"
            f"{preview}{more}\n\n"
            "Suspend them instead, keeping the flag and all scheduling?\n\n"
            "Yes  — suspend, nothing is lost (recommended)\n"
            "No   — remove the flag; these become empty cards and Tools > "
            "Empty Cards will delete their history",
            defaultno=False,
        )

    keep_for = {}
    if suspend_instead:
        for note, letter, _card in risky:
            keep_for.setdefault(note.id, set()).add(letter)
        mw.col.sched.suspend_cards([c.id for _n, _l, c in risky])

    updated = 0
    for note in notes:
        flags = normalise_flags(new_flags if new_flags is not None else note["Cards"])
        if note.id in keep_for:
            flags = normalise_flags(flags + "".join(keep_for[note.id]))
        if _apply_flags(note, flags):
            note.flush()
            updated += 1

    msg = f"Updated {updated} note(s)."
    if suspend_instead:
        msg += f" Suspended {len(risky)} card(s) rather than emptying them."
    tooltip(msg)


def sync_card_flags():
    """Rebuild _P/_W/_M/_R from the Cards field on the selected notes."""
    try:
        _sync(get_selected_notes())
    except Exception as e:
        showInfo(f"Error: {e}")


def set_card_flags():
    """Prompt for a flag string and apply it to every selected note."""
    try:
        notes = get_selected_notes()
        if not notes:
            showInfo("No notes selected. Please select notes in the browser first.")
            return
        text, ok = getText(
            "Cards to generate for the selected notes.\n\n"
            "  p = produce (English -> Japanese)\n"
            "  w = write the kanji\n"
            "  m = meaning (Japanese -> English)\n"
            "  r = read aloud (kanji, no furigana)\n\n"
            "e.g. \"pm\" or \"pmrw\". Write/read cards only appear when the "
            "note has a Kanji.",
            default="pmrw",
        )
        if not ok:
            return
        flags = normalise_flags(text)
        if not flags:
            showInfo("No valid flags given. Use any of: p w m r")
            return
        _sync(notes, new_flags=flags)
    except Exception as e:
        showInfo(f"Error: {e}")


gen_kanji_action = QAction("Generate kanji from kana", mw)
gen_romaji_action = QAction("Generate romaji from kana", mw)
sync_flags_action = QAction("Sync Japanese card flags", mw)
set_flags_action = QAction("Set Japanese card flags...", mw)
qconnect(gen_kanji_action.triggered, generate_kanji)
qconnect(gen_romaji_action.triggered, generate_romaji)
qconnect(sync_flags_action.triggered, sync_card_flags)
qconnect(set_flags_action.triggered, set_card_flags)
mw.form.menuTools.addAction(gen_kanji_action)
mw.form.menuTools.addAction(gen_romaji_action)
mw.form.menuTools.addAction(set_flags_action)
mw.form.menuTools.addAction(sync_flags_action)
