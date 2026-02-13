from datetime import datetime
import argparse
import sys
import os
import logging
from pathlib import Path
from typing import List, Optional

from playlist_maker.core.ai_service import AIService
from playlist_maker.core.library_service import LibraryService
from playlist_maker.core.matching_service import MatchingService
from playlist_maker.core.playlist_service import PlaylistService
from playlist_maker.core import constants
# CORRECTED IMPORT: logging_setup is in utils, not core
from playlist_maker.utils import logging_setup 
from playlist_maker.utils import parser_utils

def main(argv_list: Optional[List[str]] = None, clean_log_handlers: bool = True) -> dict:
    parser = argparse.ArgumentParser(description="Folder-Based Playlist Maker")
    
    # New Arguments
    parser.add_argument("--folders", nargs="+", help="List of album folder paths to process.")
    
    # Keep some existing ones for config/options
    parser.add_argument("--output-dir", default=constants.DEFAULT_OUTPUT_DIR, help="Directory to save the playlist.")
    parser.add_argument("--threshold", type=int, default=constants.DEFAULT_MATCH_THRESHOLD, help="Fuzzy match threshold.")
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    
    args = parser.parse_args(argv_list)

    # Setup Logging
    # Fix: setup_logging expects (path, mode), not level.
    # We use the default log file from constants.
    log_path = Path(constants.DEFAULT_LOG_FILE_NAME)
    logging_setup.setup_logging(log_path, "w", clean_handlers=clean_log_handlers)
    
    # Optional: Adjust level based on args if needed, though setup_logging sets its own defaults.
    # existing_level = getattr(logging, args.log_level.upper(), logging.INFO)
    # logging.getLogger().setLevel(existing_level)
    logging.info("APP: Starting Folder-Based Playlist Maker...")

    if not args.folders:
        logging.error("APP: No folders provided. Use --folders <path> ...")
        return {"error": "No folders provided."}
    
    folder_paths = [Path(p) for p in args.folders]
    
    # 1. Parse Folders -> Artist/Album List
    albums_to_process = []
    for folder in folder_paths:
        artist, album = parser_utils.extract_artist_album_from_path(folder)
        if artist: # Album might be None, but Artist is usually required for context
            albums_to_process.append((artist, album if album else ""))
            logging.info(f"APP: Parsed '{folder.name}' -> Artist: {artist}, Album: {album}")
        else:
            logging.warning(f"APP: Could not parse artist/album from '{folder.name}'. Using folder name as context if possible or skipping.")
    
    if not albums_to_process:
        return {"error": "No valid album folders found to process."}

    # Load Configuration
    import configparser
    config = configparser.ConfigParser()
    # Assuming config file is in the project root or same dir as run_gui.py
    # We can try to locate it relative to this file or current working directory.
    config_path = Path("playlist_maker.conf") # CWD based
    if not config_path.exists():
        # Try relative to package
        config_path = Path(__file__).parent.parent / "playlist_maker.conf"

    if config_path.exists():
        config.read(config_path)
        logging.info(f"APP: Loaded config from {config_path}")
    else:
        logging.warning("APP: Config file 'playlist_maker.conf' not found. Using defaults/env vars.")

    # 2. Initialize Services
    try:
        # AI Service
        # Get API key from config if available, let AIService fallback to env var if None
        api_key = config.get("AI", "api_key", fallback=None)
        # Handle the case where key might be empty string in config
        if api_key and not api_key.strip(): api_key = None
        
        ai_model = config.get("AI", "model", fallback=constants.DEFAULT_AI_MODEL)

        ai_service = AIService(api_key=api_key, default_model=ai_model) 
        if not ai_service.client:
            return {"error": "AI Service could not be initialized. Please set GOOGLE_API_KEY env var or 'api_key' in playlist_maker.conf."}

        # Library Service (Filesystem Scan only)
        # We don't need a DB for this mode, passing None
        library_service = LibraryService(db_path=None)
        
        
        # Matching Service initialized later when needed
        # matching_service = MatchingService(library_service)
        
        # Playlist Service
        playlist_service = PlaylistService()
        
    except Exception as e:
        logging.error(f"APP: Failed to initialize services: {e}", exc_info=True)
        return {"error": f"Service initialization failed: {e}"}

    # 3. AI: Get Tracks
    logging.info("APP: Requesting track list from AI...")
    try:
        # We request tracks for ALL parsed albums in one go (or could batch if too many)
        ai_tracks = ai_service.get_critically_acclaimed_tracks(albums_to_process)
        logging.info(f"APP: AI returned {len(ai_tracks)} tracks.")
        logging.info(f"APP: AI tracks: {ai_tracks}")
    except Exception as e:
        logging.error(f"APP: AI generation failed: {e}", exc_info=True)
        return {"error": f"AI generation failed: {e}"}

    if not ai_tracks:
        return {"error": "AI returned no tracks."}

    # 4. Library: Scan Folders
    logging.info("APP: Scanning local folders for audio files...")
    supported_exts = constants.DEFAULT_SUPPORTED_EXTENSIONS # e.g. .mp3, .flac
    library_service.scan_folders_into_memory(folder_paths, supported_exts)
    
    import re # Ensure re is imported
    # Compile regex for stripping parenthetical keywords
    strip_keywords = constants.DEFAULT_PARENTHETICAL_STRIP_KEYWORDS
    # Escape keywords to be safe, though they are usually simple words
    strip_keywords_regex_str = r'\b(?:' + '|'.join(re.escape(k) for k in strip_keywords) + r')\b'
    parenthetical_strip_regex = re.compile(strip_keywords_regex_str, re.IGNORECASE)

    # 5. Matching
    logging.info("APP: Matching AI tracks to local files...")
    
    # Instantiate MatchingService
    # We set interactive_mode=False to allow the service to make 'best effort' auto-matches 
    # and return None if ambiguous, rather than returning an InteractionRequired object 
    # which we'd have to handle with complex CLI prompts here. 
    # If the user wants interactive, we'd need to port the CLI prompt logic. 
    # For now, auto-match is safer for this refactor.
    matching_service = MatchingService(interactive_mode=False)

    final_playlist_tracks = []
    skipped_tracks = []
    
    current_index = library_service.library_index_memory
    
    for input_artist, input_title in ai_tracks:
        match_result = matching_service.find_best_track_match(
            input_artist=input_artist,
            input_track=input_title,
            match_threshold=args.threshold,
            live_penalty_factor=constants.DEFAULT_LIVE_PENALTY_FACTOR,
            current_library_index=current_index,
            parenthetical_strip_regex=parenthetical_strip_regex
        )
        
        if match_result and isinstance(match_result, dict) and "path" in match_result:
            final_playlist_tracks.append(Path(match_result["path"]))
            logging.info(f"APP: Matched '{input_artist} - {input_title}' -> {Path(match_result['path']).name}")
        else:
            skipped_tracks.append(f"{input_artist} - {input_title}")
            logging.warning(f"APP: No clear match for '{input_artist} - {input_title}'") # Log as warning

    logging.info(f"APP: Matched {len(final_playlist_tracks)} tracks. Skipped {len(skipped_tracks)}.")

    # 6. Generate Playlist
    # 6. Generate Playlist
    if final_playlist_tracks:
        # Construct M3U Content
        m3u_lines = ["#EXTM3U"]
        for track_path in final_playlist_tracks:
            # Simple M3U format: 
            # #EXTINF:123,Artist - Title
            # /path/to/file.mp3
            # We might not have metadata here easily if MatchingService didn't return it full.
            # MatchingService returns absolute paths (Path objects).
            # We can try to get metadata or just valid M3U entries.
            # For now, let's just put the path. 
            # Actually, standard is #EXTINF:-1,Filename if unknown duration/meta
            m3u_lines.append(f"#EXTINF:-1,{track_path.name}")
            m3u_lines.append(str(track_path))

        # Prepare arguments for write_m3u_and_missing_files
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        playlist_name = f"AI_Selected_{timestamp}.m3u"
        output_dir = Path(args.output_dir)
        output_m3u_path = output_dir / playlist_name
        
        # Missing tracks formatting
        # skipped_tracks is likely a list of tuples or strings from matching service
        formatted_skipped = [str(t) for t in skipped_tracks]

        try:
            output_info = playlist_service.write_m3u_and_missing_files(
                m3u_lines_content=m3u_lines,
                skipped_track_inputs_for_file=formatted_skipped,
                output_m3u_filepath=output_m3u_path,
                mpd_playlist_dir_str=None, # Argument to be added if MPD CLI arg exists, but for now None or from config if loaded
                missing_tracks_dir_path=Path(constants.DEFAULT_MISSING_TRACKS_DIR),
                input_playlist_path_for_header="Folder Selection (AI Generated)",
                total_input_tracks=len(ai_tracks)
            )
            
            playlist_path = output_info.get("m3u_path")
            logging.info(f"APP: Playlist created at: {playlist_path}")
            return {
                "success": True, 
                "playlist_path": str(playlist_path), 
                "skipped_tracks": skipped_tracks
            }
        except Exception as e:
             logging.error(f"APP: Error writing playlist: {e}", exc_info=True)
             return {"error": f"Error writing playlist: {e}"}
    else:
        logging.warning("APP: No tracks were matched. No playlist created.")
        return {
            "success": False, 
            "error": "No tracks matched.", 
            "skipped_tracks": skipped_tracks
        }

if __name__ == "__main__":
    result = main()
    # print(json.dumps(result)) # If we want to pipe JSON out
    sys.exit(0 if result.get("success") else 1)