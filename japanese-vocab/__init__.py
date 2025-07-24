import sys
import os
from typing import Optional, List
import json
import urllib.request
import urllib.parse
import urllib.error

from aqt import mw
from aqt.utils import showInfo, qconnect, tooltip
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

gen_kanji_action = QAction("Generate kanji from kana", mw)
gen_romaji_action = QAction("Generate romaji from kana", mw)
qconnect(gen_kanji_action.triggered, generate_kanji)
qconnect(gen_romaji_action.triggered, generate_romaji)
mw.form.menuTools.addAction(gen_kanji_action)
mw.form.menuTools.addAction(gen_romaji_action)
