# playlist_maker/core/ai_service.py
import os
import json
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

    def generate_playlist_from_prompt(self, prompt: str, model_override: Optional[str]) -> List[Tuple[str, str]]:
        """
        Sends a prompt to the AI and expects a list of (Artist, Song) tuples.
        Uses Google Gemini's generate_content with a tool for structured JSON output.
        """
        if not self.client:
            logging.error("AI_SVC: Google GenAI client not initialized (missing API key or library). Cannot generate playlist.")
            raise ConnectionError("AI client not initialized. Check API key and ensure 'google-genai' library is installed.")

        target_model = model_override if model_override else self.default_model
        logging.info(f"AI_SVC: Requesting playlist from model '{target_model}' with prompt: '{prompt}'")

        # Define the tool for structured output using types.Tool and FunctionDeclaration
        # This approach ensures strict adherence to the desired schema.
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
                tools=[playlist_tool],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode='ANY',
                        allowed_function_names=['create_song_playlist']
                    )
                ),
                system_instruction="You are a helpful playlist assistant. Your task is to generate a list of songs based on the user's prompt. Please use the provided 'create_song_playlist' tool to format your response as a structured playlist."
            )
            
            response = self.client.models.generate_content(
                model=target_model,
                contents=prompt,
                config=config
            )

            # In the new SDK, response.function_calls is a convenient way to access tool calls.
            tool_call = None
            if response.function_calls:
                tool_call = response.function_calls[0]

            if tool_call and tool_call.name == "create_song_playlist":
                # tool_call.args is a dictionary containing the structured output.
                playlist_data = tool_call.args

                tracks = []
                for item in playlist_data.get("playlist", []):
                    artist = item.get("artist")
                    song = item.get("song")
                    if artist and song:
                        tracks.append((str(artist).strip(), str(song).strip()))
                    else:
                        logging.warning(f"AI_SVC: Received incomplete track item from AI: {item}")
                
                if not tracks:
                    logging.warning(f"AI_SVC: AI returned an empty playlist or malformed data for prompt: '{prompt}'. Data: {playlist_data}")
                return tracks
            else:
                logging.error(f"AI_SVC: AI did not use the 'create_song_playlist' tool as expected. Response received: {response}")
                return []

        except Exception as e: # Catch any exception during API call
            logging.error(f"AI_SVC: Error during Gemini API call to '{target_model}': {e}", exc_info=True)
            raise ConnectionError(f"AI API call failed: {e}")
