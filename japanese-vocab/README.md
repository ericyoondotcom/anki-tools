# Japanese Vocab Utils
Utilities for working with Japanese vocab cards using OpenAI to generate kanji and romaji.

## Installation

1. Create a symlink from this folder to your Anki add-ons directory:
   ```bash
   ln -s /path/to/repo/japanese-vocab ~/Library/Application\ Support/Anki2/addons21/japanese-vocab
   ```

2. Restart Anki and configure your OpenAI API key (see Config section below).

## Config
Please specify the add-on config like so:
```json
{
    "openai_key": "your_openai_api_key_here"
}
```

Fields:
- `openai_key`: this project uses OpenAI LLMs to generate data. Please input your key here

To set the config:
1. Go to Tools → Add-ons
2. Select "Japanese Vocab Utils"
3. Click "Config"
4. Add your OpenAI API key

## Fields specification
For this add-on to work, your note fields must be exactly named as follows:
- `English`: The English meaning of the word
- `Romanji` [sic]: The romanized pronunciation of the word
- `Kana`: The kana (hiragana or katakana) spelling of the word
- `Kanji`: The kanji spelling of the word

## Usage

### Generate Kanji from Kana + Meaning
1. In the browser, select notes that have `Kana` and `English` fields filled but empty `Kanji` fields
2. Go to Tools → "Generate kanji from kana"
3. The add-on will use OpenAI to generate appropriate kanji spellings

### Generate Romaji From Kana
1. In the browser, select notes that have `Kana` fields filled but empty `Romanji` fields
2. Go to Tools → "Generate romaji from kana"
3. The add-on will convert the kana to standard Hepburn romanization

## Notes
- The add-on only processes selected notes in the browser
- It skips notes that already have the target field filled
- Uses OpenAI's gpt-4o-mini model with JSON responses for reliable results
- No external dependencies required - uses Python's built-in urllib for HTTP requests
