# playlist_maker/core/ai_service.py
import os
import json
import csv
import io
import logging
from typing import Optional, List, Tuple, Dict, Any, Union

# Ensure you have `pip install google-genai` and add it to requirements.txt
try:
    from google import genai
    from google.genai import types
except ImportError:
    # Define dummy classes for type hinting and to avoid immediate failure on import
    # if the library is not installed.
    class genai:
        class Client: pass
    class types:
        class GenerateContentConfig: pass
        class Tool: pass
        class ToolConfig: pass
        class FunctionCallingConfig: pass
        class FunctionDeclaration: pass
        class Schema: pass
        class Part: pass

class AIService:
    def __init__(self, api_key: Optional[str], default_model: str) -> None:
        self.client: Optional[genai.Client] = None
        self.default_model: str = default_model
        
        effective_api_key = api_key
        if not effective_api_key:
            # Support both GOOGLE_API_KEY and GEMINI_API_KEY
            effective_api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        
        if not effective_api_key:
            logging.warning("AI_SVC: Google API key not provided (checked config/args and GOOGLE_API_KEY/GEMINI_API_KEY env vars). "
                          "AI features will be disabled.")
            return # Client remains None
        
        try:
            # Re-import to ensure we are using the actual library
            from google import genai
            self.client = genai.Client(api_key=effective_api_key)
            logging.info("AI_SVC: Google GenAI client initialized successfully.")
        except ImportError:
            msg = "google-genai library not installed. AI features are unavailable. Please run 'pip install google-genai'."
            logging.error(f"AI_SVC: {msg}")
            # We don't raise here to allow the application to start;
            # errors will be raised when generate_playlist_from_prompt is called.
        except Exception as e:
            logging.error(f"AI_SVC: Failed to initialize Google GenAI client: {e}", exc_info=True)
            self.client = None # Ensure client is None on failure

    def get_critically_acclaimed_tracks(self, albums: List[Tuple[str, str]], model_override: Optional[str] = None) -> List[Tuple[str, str]]:
        """
        Takes a list of (Artist, Album) tuples and requests 12-25 critically acclaimed tracks.
        """
        if not self.client:
            raise ConnectionError("AI client not initialized.")

        # Construct valid CSV content with proper escaping for commas/quotes/newlines
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(["Artist", "Album"])
        for artist, album in albums:
            writer.writerow([artist, album])
        csv_content = buffer.getvalue()
            
        prompt_part = types.Part.from_text(
            text=(
                """I am sending a CSV attachment of music album titles and the corresponding artists. 
                Use this list and search the web to find 12-25 critically acclaimed or popular 
                music tracks from these albums, then return this list. Make sure that only tracks that are actually from the albums listed are included."""
            )
        )
        
        csv_part = types.Part.from_bytes(
            data=csv_content.encode('utf-8'),
            mime_type='text/csv'
        )
        logging.info(f"AI_SVC: Prepared CSV content for AI prompt:\n{csv_content}")
        return self._generate_structured_playlist([prompt_part, csv_part], model_override)

    def _generate_structured_playlist(self, contents: Union[str, List[Any]], model_override: Optional[str]) -> List[Tuple[str, str]]:
        """
        Shared logic for sending prompt and getting structured response.
        """
        target_model = model_override if model_override else self.default_model
        logging.info(f"AI_SVC: Requesting playlist from '{target_model}'")

        playlist_tool = types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="create_song_playlist",
                    description="Creates a playlist of songs, each with an artist and song title.",
                    parameters=types.Schema(
                        type='OBJECT',
                        properties={
                            'playlist': types.Schema(
                                type='ARRAY',
                                description="A list of songs, each item an object with 'artist' and 'song' properties.",
                                items=types.Schema(
                                    type='OBJECT',
                                    properties={
                                        'artist': types.Schema(type='STRING', description="The name of the artist performing the song."),
                                        'song': types.Schema(type='STRING', description="The title of the song.")
                                    },
                                    required=['artist', 'song']
                                )
                            )
                        },
                        required=['playlist']
                    )
                )
            ]
        )

        try:
            config = types.GenerateContentConfig(
                tools=[playlist_tool,types.Tool(google_search=types.GoogleSearch())],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode='ANY',
                        allowed_function_names=['create_song_playlist']
                    )
                ),
                system_instruction="You are a helpful playlist assistant. Your task is to generate a list of songs based on the user's prompt using the provided tool."
            )
            
            response = self.client.models.generate_content(
                model=target_model,
                contents=contents,
                config=config
            )
            
            logging.info(f"AI_SVC: Full API Response: {response}")

            tool_call = None
            if response.function_calls:
                tool_call = response.function_calls[0]

            if tool_call and tool_call.name == "create_song_playlist":
                playlist_data = tool_call.args
                tracks = []
                for item in playlist_data.get("playlist", []):
                    artist = item.get("artist")
                    song = item.get("song")
                    if artist and song:
                        tracks.append((str(artist).strip(), str(song).strip()))
                return tracks
            else:
                logging.error(f"AI_SVC: AI did not use the tool. Response: {response}")
                return []

        except Exception as e:
            # Try to extract detailed error info if available (e.g. from google.genai.errors)
            error_details = str(e)
            if hasattr(e, 'status_code'):
                error_details = f"Status: {e.status_code}, " + error_details
            if hasattr(e, 'message'):
                error_details += f", Message: {e.message}"
                
            logging.error(f"AI_SVC: Gemini API Call Failed. Details: {error_details}", exc_info=True)
            raise ConnectionError(f"AI API call failed: {error_details}")
