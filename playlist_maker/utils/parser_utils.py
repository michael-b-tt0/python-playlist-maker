import re
from pathlib import Path
from typing import Tuple, Optional

def extract_artist_album_from_path(folder_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts artist and album name from a folder name using regex.
    Logic ported from album_artist_csv_maker.ipynb.
    
    Expected folder format examples:
    - "Coach Party - Caramel" -> Artist: "Coach Party", Album: "Caramel"
    - "Limp Bizkit - Making Love to Morgan Wallen" -> ...
    - "(2022) Nova Twins - Parasites & Butterflies" -> Artist: "Nova Twins", ... (strips leading year/parens)
    """
    folder_name = folder_path.name
    
    # split(..., maxsplit=1) logic to separate Artist/Album from folder name.
    # The regex r"\s*(?:—|\s-\s)\s*" handles " - " or "—" as separators.
    # The inner re.split(r"[\(\[\{]", n, 1)[0] removes leading/trailing metadata in brackets like (2022) or [2022] often found at START if it was "Artist - Album". 
    # WAIT, the notebook logic was: re.split(r"[\(\[\{]", n, 1)[0].strip() applied to the *result*? 
    # Let's check the notebook again. 
    # rows = [ re.split(..., re.split(r"[\(\[\{]", n, 1)[0].strip(), maxsplit=1) for n in names ]
    # It takes the folder name 'n', splits by '(', '[', or '{', takes the first part (stripping things like " (2022)"), then strips whitespace.
    # Then it splits that result by " - " or "—".
    
    # 1. Cleaning: Remove anything starting with (, [, or {
    # Actually, looking at the notebook output:
    # "12       Whitelands  Night-bound Eyes Are Blind To The Day"
    # It likely expects "Artist - Album".
    
    # Let's replicate the notebook logic EXACTLY first.
    
    # Step 1: Remove potentially leading/trailing parenthetical extensions if they appear AFTER the main text?
    # notebook: re.split(r"[\(\[\{]", n, 1)[0]
    # If n is "Artist - Album (2022)", this keeps "Artist - Album ".
    # If n is "(2022) Artist - Album", this keeps "" (empty string) because it splits at index 0! 
    # Wait, the notebook output for "10      Viagra Boys                            viagr aboys" suggests it works. 
    # Let's assume the folders are "Artist - Album".
    
    cleaned_name = re.split(r"[\(\[\{]", folder_name, 1)[0].strip()
    
    if not cleaned_name:
         # Fallback if the folder started with ( and became empty? 
         # Or maybe the intention was to remove trailing info.
         cleaned_name = folder_name

    parts = re.split(r"\s*(?:—|\s-\s)\s*", cleaned_name, maxsplit=1)
    
    artist = parts[0].strip()
    album = None
    
    if len(parts) > 1:
        # Notebook: r[1].strip().rstrip("-–— ").strip()
        album = parts[1].strip().rstrip("-–— ").strip()
        
    return artist, album
