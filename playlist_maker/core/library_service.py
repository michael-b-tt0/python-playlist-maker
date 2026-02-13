# playlist_maker/core/library_service.py
import sqlite3
import os
import sys
import time
from pathlib import Path
import logging
import re
from typing import Optional, Dict, List, Tuple, Any

import mutagen
import mutagen.mp3, mutagen.flac, mutagen.oggvorbis, mutagen.mp4

# Only import normalization utils if needed, or keep for consistency
from playlist_maker.utils.normalization_utils import (
    normalize_and_detect_specific_live_format
)
# Mock Colors/Symbols if missing or keep imports if available
try:
    from playlist_maker.ui.cli_interface import Colors, Symbols, colorize
except ImportError:
    class Colors: CYAN = ""; MAGENTA = ""; BLUE = ""; GREEN = ""; RED = ""; YELLOW = ""; RESET = ""
    class Symbols: INFO = ""; ARROW = ""; FAILURE = ""; SUCCESS = ""; WARNING = ""
    def colorize(text, color): return text

class LibraryService:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        """
        Initialize LibraryService.
        For Folder Mode: db_path can be None, as we will use in-memory scanning.
        """
        self.db_path = db_path
        self.library_index_memory: List[Dict[str, Any]] = [] 

    def scan_folders_into_memory(self, folder_paths: List[Path], supported_extensions: Tuple[str, ...]) -> int:
        """
        Scans specific folders and populates library_index_memory.
        Returns number of tracks found.
        """
        self.library_index_memory = []
        total_tracks = 0
        
        if isinstance(supported_extensions, list):
            supported_extensions = tuple(supported_extensions)

        print(f"Scanning {len(folder_paths)} folders...")
        
        for folder in folder_paths:
            if not folder.exists():
                logging.warning(f"Skipping non-existent folder: {folder}")
                continue
                
            for root, _, files in os.walk(folder):
                for file_name in files:
                    if file_name.lower().endswith(supported_extensions):
                        file_path = Path(root) / file_name
                        try:
                            meta_artist, meta_title, meta_album, meta_duration = self.get_file_metadata(file_path)
                            
                            # Normalize for matching
                            # We can keep it simple or use the complex normalization if matching needs it.
                            # The matching service likely relies on 'norm_*' fields.
                            
                            # Simple stripping for now, matching service might re-normalize or expect these field names
                            norm_title = self._simple_normalize(meta_title)
                            norm_artist = self._simple_normalize(meta_artist)
                            norm_filename = self._simple_normalize(file_path.stem)
                            
                            track_entry = {
                                "path": str(file_path.resolve()),
                                "artist": meta_artist,
                                "title": meta_title,
                                "album": meta_album,
                                "duration": meta_duration,
                                "filename_stem": file_path.stem,
                                "norm_artist_stripped": norm_artist,
                                "norm_title_stripped": norm_title,
                                "norm_filename_stripped": norm_filename,
                                "entry_is_live": False # Default
                            }
                            self.library_index_memory.append(track_entry)
                            total_tracks += 1
                        except Exception as e:
                            logging.warning(f"Error reading {file_path}: {e}")
                            
        logging.info(f"Scanned {total_tracks} tracks into memory.")
        return total_tracks

    def _simple_normalize(self, text: str) -> str:
        if not text: return ""
        return re.sub(r'[^a-z0-9]', '', text.lower())

    def get_library_index(self) -> List[Dict[str, Any]]:
        return self.library_index_memory

    def get_file_metadata(self, file_path_obj: Path) -> Tuple[str, str, str, Optional[int]]:
        artist, title, album, duration = "", "", "", None
        try:
            audio = mutagen.File(file_path_obj, easy=True)
            detailed_audio = mutagen.File(file_path_obj)
            if audio:
                artist_tags = audio.get("artist", []) or audio.get("albumartist", []) or audio.get("performer", [])
                artist = artist_tags[0].strip() if artist_tags else ""
                title_tags = audio.get("title", [])
                title = title_tags[0].strip() if title_tags else ""
                album_tags = audio.get("album", [])
                album = album_tags[0].strip() if album_tags else ""
            
            if detailed_audio and hasattr(detailed_audio, 'info') and hasattr(detailed_audio.info, 'length'):
                 duration = int(detailed_audio.info.length)
        except Exception as e:
            logging.debug(f"Metadata error for {file_path_obj}: {e}")
        return artist, title, album, duration