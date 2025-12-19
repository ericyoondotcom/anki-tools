import json

# Configuration
DECK_NAME = "Music Theory::Scale Degrees"
MODEL_NAME = "Basic"

# Data Definitions
keys = [
    "C", "G", "D", "A", "E", "B", "F#", "C#",
    "F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb"
]

# Mapping notes for major scales
# Note: This is a simplified representation for the sake of the script logic
scale_notes = {
    "C":  ["C", "D", "E", "F", "G", "A", "B"],
    "G":  ["G", "A", "B", "C", "D", "E", "F#"],
    "D":  ["D", "E", "F#", "G", "A", "B", "C#"],
    "A":  ["A", "B", "C#", "D", "E", "F#", "G#"],
    "E":  ["E", "F#", "G#", "A", "B", "C#", "D#"],
    "B":  ["B", "C#", "D#", "E", "F#", "G#", "A#"],
    "F#": ["F#", "G#", "A#", "B", "C#", "D#", "E#"],
    "C#": ["C#", "D#", "E#", "F#", "G#", "A#", "B#"],
    "F":  ["F", "G", "A", "Bb", "C", "D", "E"],
    "Bb": ["Bb", "C", "D", "Eb", "F", "G", "A"],
    "Eb": ["Eb", "F", "G", "Ab", "Bb", "C", "D"],
    "Ab": ["Ab", "Bb", "C", "Db", "Eb", "F", "G"],
    "Db": ["Db", "Eb", "F", "Gb", "Ab", "Bb", "C"],
    "Gb": ["Gb", "Ab", "Bb", "Cb", "Db", "Eb", "F"],
    "Cb": ["Cb", "Db", "Eb", "Fb", "Gb", "Ab", "Bb"]
}

degrees_roman = ["I", "II", "III", "IV", "V", "VI", "VII"]

def create_notes():
    # Ensure the deck exists
    deck_id = mw.col.decks.id(DECK_NAME)
    mw.col.decks.select(deck_id)
    
    # Get the model and set it as the current model for the collection
    model = mw.col.models.byName(MODEL_NAME)
    if not model:
        print(f"Error: Model '{MODEL_NAME}' not found.")
        return
    
    # Set the model to ensure mw.col.newNote(False) uses the correct template
    mw.col.models.setCurrent(model)

    notes_created = 0

    for key_name, notes in scale_notes.items():
        for i, note in enumerate(notes):
            roman = degrees_roman[i]
            
            # Card 1: Degree to Note (e.g., V of C major -> G)
            f1 = f"{roman} of {key_name} major"
            b1 = note
            
            # Card 2: Note to Degree (e.g., G in C major -> V)
            f2 = f"{note} in {key_name} major"
            b2 = roman

            # Create Note 1
            note1 = mw.col.newNote(False)
            note1.model()['did'] = deck_id
            note1.fields[0] = f1
            note1.fields[1] = b1
            mw.col.addNote(note1)
            
            # Create Note 2
            note2 = mw.col.newNote(False)
            note2.model()['did'] = deck_id
            note2.fields[0] = f2
            note2.fields[1] = b2
            mw.col.addNote(note2)
            
            notes_created += 2

    mw.col.reset()
    mw.reset()
    print(f"Successfully created {notes_created} notes in '{DECK_NAME}'.")

# Execute
create_notes()