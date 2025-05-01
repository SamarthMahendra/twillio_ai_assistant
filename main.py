import os
import json
import asyncio
import base64
import audioop
import logging
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from dotenv import load_dotenv
from twilio.twiml.voice_response import VoiceResponse, Connect
from google.genai import Client as GenAIClient
from google.genai import types as genai_types
from google.api_core.exceptions import ClientError
from fastapi.websockets import WebSocketState

# --- Configuration & Setup ---
load_dotenv()

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Environment Variables ---
PORT = int(os.getenv('PORT', 5050))
TWILIO_SAMPLE_RATE = 8000
GEMINI_INPUT_SAMPLE_RATE = 16000
GEMINI_OUTPUT_SAMPLE_RATE = 24000
# Use a model compatible with the Live API
# Check availability, e.g., gemini-1.5-flash-preview-0514 or gemini-2.0-flash-live-001
GEMINI_MODEL = os.getenv('GEMINI_MODEL', "gemini-1.5-flash-preview-0514")
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY') # Ensure this is set!

if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY environment variable not set.")
    # Optionally, raise an error or exit if the key is mandatory
    # raise ValueError("GEMINI_API_KEY must be set")

# --- FastAPI App ---
app = FastAPI()

# --- Google GenAI Client ---
# Configure the client. It will use the API key from the environment.
try:
    genai_client = GenAIClient(api_key=GEMINI_API_KEY)
except Exception as e:
    logger.error(f"Failed to initialize Google GenAI Client: {e}")
    genai_client = None # Handle cases where client init fails

# --- Audio Conversion Functions ---

def pcm_to_ulaw(pcm_data: bytes, sample_rate: int, target_rate: int = TWILIO_SAMPLE_RATE) -> bytes:
    """Converts 16-bit PCM audio to 8-bit µ-law."""
    try:
        # Resample if necessary (e.g., Gemini 24kHz -> Twilio 8kHz)
        if sample_rate != target_rate:
            pcm_data, _ = audioop.ratecv(pcm_data, 2, 1, sample_rate, target_rate, None)

        # Convert linear PCM to µ-law
        ulaw_data = audioop.lin2ulaw(pcm_data, 2)
        return ulaw_data
    except audioop.error as e:
        logger.error(f"Audioop error during PCM to µ-law conversion: {e}")
        return b"" # Return empty bytes on error

def ulaw_to_pcm(ulaw_data: bytes, sample_rate: int = TWILIO_SAMPLE_RATE, target_rate: int = GEMINI_INPUT_SAMPLE_RATE) -> bytes:
    """Converts 8-bit µ-law audio to 16-bit PCM."""
    try:
        # Convert µ-law to 16-bit linear PCM
        pcm_data = audioop.ulaw2lin(ulaw_data, 2)

        # Resample if necessary (e.g., Twilio 8kHz -> Gemini 16kHz)
        if sample_rate != target_rate:
            pcm_data, _ = audioop.ratecv(pcm_data, 2, 1, sample_rate, target_rate, None)

        return pcm_data
    except audioop.error as e:
        logger.error(f"Audioop error during µ-law to PCM conversion: {e}")
        return b"" # Return empty bytes on error

# --- FastAPI Routes ---

@app.get("/", response_class=JSONResponse)
async def index_page():
    return {"message": "Gemini Live API Proxy Server for Twilio is running!"}

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handles incoming Twilio call and responds with TwiML to connect WebSocket."""
    host = request.url.hostname
    # Ensure host is available, provide a default or handle error if needed
    if not host:
        logger.error("Could not determine hostname from request.")
        return HTMLResponse(content="Error: Could not determine server hostname.", status_code=500)

    logger.info(f"Incoming call received. Connecting WebSocket to wss://{host}/media-stream")

    response = VoiceResponse()
    connect = Connect()
    # Connect to the /media-stream endpoint using WebSocket Secure (wss)
    connect.stream(url=f'wss://{host}/media-stream')
    response.append(connect)

    return HTMLResponse(content=str(response), media_type="application/xml")

# --- WebSocket Handler ---

# Store active Twilio stream SIDs (could use a more robust cache/DB if needed)
twilio_stream_sids = {}

async def handle_twilio_to_gemini(twilio_ws: WebSocket, gemini_session, stream_sid: str):
    """Receives messages from Twilio, converts audio, and sends to Gemini."""
    logger.info(f"[{stream_sid}] Starting Twilio listener task.")
    try:
        while True:
            message = await twilio_ws.receive_text()
            data = json.loads(message)
            event = data.get("event")

            if event == "connected":
                logger.info(f"[{stream_sid}] Twilio stream connected.")
            elif event == "start":
                rcvd_stream_sid = data.get("streamSid")
                logger.info(f"[{rcvd_stream_sid}] Twilio stream started: {data}")
                # Store potentially updated streamSid if needed, though usually matches initial
                twilio_stream_sids[twilio_ws] = rcvd_stream_sid
            elif event == "media":
                # sequence = data.get("sequenceNumber") # Useful for debugging ordering
                payload = data['media']['payload']
                # logger.debug(f"[{stream_sid}] Received media chunk {sequence}")
                if payload:
                    decoded_ulaw = base64.b64decode(payload)
                    pcm_audio = ulaw_to_pcm(decoded_ulaw, TWILIO_SAMPLE_RATE, GEMINI_INPUT_SAMPLE_RATE)
                    if pcm_audio and gemini_session:
                        # Send raw PCM audio bytes using send_realtime_input
                        await gemini_session.send_realtime_input(
                             audio=genai_types.Blob(data=pcm_audio, mime_type=f"audio/pcm;rate={GEMINI_INPUT_SAMPLE_RATE}")
                        )
                        # logger.debug(f"[{stream_sid}] Sent {len(pcm_audio)} bytes PCM to Gemini.")
            elif event == "mark":
                # Useful for knowing Twilio is still active, can be ignored or logged
                mark_name = data.get("mark", {}).get("name")
                # logger.info(f"[{stream_sid}] Received Twilio mark: {mark_name}")
                pass # No action needed for basic proxy
            elif event == "stop":
                logger.info(f"[{stream_sid}] Twilio stream stopped.")
                # Signal end of audio stream to Gemini if using automatic VAD
                # Note: Check if this causes issues with Gemini expecting more turns
                if gemini_session:
                     # Pass audio_stream_end=True if stream pauses or ends
                     # await gemini_session.send_realtime_input(audio_stream_end=True)
                     logger.info(f"[{stream_sid}] Signalled audio stream end to Gemini (optional).")
                break # Exit loop on stop event
            else:
                logger.warning(f"[{stream_sid}] Received unknown Twilio event: {event}")

    except WebSocketDisconnect:
        logger.info(f"[{stream_sid}] Twilio WebSocket disconnected.")
    except Exception as e:
        logger.error(f"[{stream_sid}] Error in Twilio listener: {e}", exc_info=True)
    finally:
        logger.info(f"[{stream_sid}] Twilio listener task finished.")
        # Clean up SID mapping
        if twilio_ws in twilio_stream_sids:
            del twilio_stream_sids[twilio_ws]
        # Consider closing Gemini session here or letting the gather handle it

async def handle_gemini_to_twilio(gemini_session, twilio_ws: WebSocket, stream_sid: str):
    """Receives messages from Gemini, converts audio, and sends to Twilio."""
    logger.info(f"[{stream_sid}] Starting Gemini listener task.")
    if not stream_sid:
        logger.error("Cannot send audio to Twilio without a stream_sid.")
        return
    try:
        async for response in gemini_session.receive():
            # Log token usage if available
            if response.usage_metadata:
                logger.info(f"[{stream_sid}] Gemini Token Usage: {response.usage_metadata.total_token_count} total tokens.")

            # Handle potential errors from Gemini
            if response.error:
                 logger.error(f"[{stream_sid}] Received error from Gemini: {response.error}")
                 # Optionally, send a message back via Twilio?
                 break # Stop processing on error

            # Check for actual audio data in the response
            # Response structure might vary slightly based on SDK version / API changes
            audio_data = None
            if response.server_content:
                 # The Live API sends audio data directly in response.data sometimes
                 # Or potentially nested within server_content.model_turn.parts[0].inline_data
                 # Check both common patterns - adjust based on observed responses
                 if response.data:
                      audio_data = response.data
                 elif response.server_content.model_turn and response.server_content.model_turn.parts:
                      first_part = response.server_content.model_turn.parts[0]
                      if first_part.inline_data and first_part.inline_data.mime_type.startswith("audio/"):
                           audio_data = first_part.inline_data.data

            if audio_data:
                # Gemini Live API outputs 16-bit PCM at 24kHz
                ulaw_audio = pcm_to_ulaw(audio_data, GEMINI_OUTPUT_SAMPLE_RATE, TWILIO_SAMPLE_RATE)
                if ulaw_audio:
                    encoded_ulaw = base64.b64encode(ulaw_audio).decode('utf-8')
                    twilio_media_message = {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {
                            "payload": encoded_ulaw
                        }
                    }
                    await twilio_ws.send_text(json.dumps(twilio_media_message))
                    # logger.debug(f"[{stream_sid}] Sent {len(ulaw_audio)} bytes µ-law to Twilio.")

            # Handle other events like interruptions, generation complete etc.
            if response.server_content:
                 if response.server_content.interrupted is True:
                      logger.info(f"[{stream_sid}] Gemini generation interrupted.")
                 if response.server_content.generation_complete is True:
                      logger.info(f"[{stream_sid}] Gemini generation complete.")

            if response.go_away:
                 logger.warning(f"[{stream_sid}] Received GoAway from Gemini, connection closing soon: {response.go_away.time_left}s")

    except ClientError as e:
         logger.error(f"[{stream_sid}] Gemini API client error: {e}", exc_info=True)
    except WebSocketDisconnect:
        # This might happen if the Gemini session closes from their end
        logger.info(f"[{stream_sid}] Gemini session WebSocket disconnected.")
    except Exception as e:
        logger.error(f"[{stream_sid}] Error in Gemini listener: {e}", exc_info=True)
    finally:
        logger.info(f"[{stream_sid}] Gemini listener task finished.")
        # Ensure Twilio connection is closed if Gemini stops
        if twilio_ws.client_state != WebSocketState.DISCONNECTED:
             await twilio_ws.close(code=1000) # Normal closure
             logger.info(f"[{stream_sid}] Closed Twilio WebSocket from Gemini handler.")


@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handles the WebSocket connection from Twilio."""
    await websocket.accept()
    logger.info("Twilio WebSocket client connected.")

    stream_sid = None
    gemini_session = None

    # --- Wait for the 'start' message to get the streamSid ---
    try:
        # The first message *should* be 'connected', followed by 'start'
        # We need the 'start' message for the streamSid.
        while stream_sid is None:
             message = await websocket.receive_text()
             data = json.loads(message)
             if data.get("event") == "start":
                  stream_sid = data.get("streamSid")
                  twilio_stream_sids[websocket] = stream_sid # Store SID linked to WS object
                  logger.info(f"[{stream_sid}] Received start event. Stream SID: {stream_sid}")
                  break # Got the SID, proceed
             elif data.get("event") == "connected":
                  logger.info("Received connected event.") # Keep waiting for start
             else:
                  logger.warning(f"Received unexpected event {data.get('event')} before start.")
                  # Maybe wait a bit more or handle error? For now, keep waiting.

        if not stream_sid:
             logger.error("Did not receive streamSid from Twilio start event. Closing connection.")
             await websocket.close(code=1011) # Internal error
             return

        if not genai_client:
            logger.error(f"[{stream_sid}] GenAI client not initialized. Cannot proceed.")
            await websocket.close(code=1011)
            return

        # --- Configure and Connect to Gemini Live API ---
        logger.info(f"[{stream_sid}] Connecting to Gemini Live API model: {GEMINI_MODEL}")

            # *** Use LiveConnectConfig, but OMIT realtime_input_config ***
        config = genai_types.LiveConnectConfig(
            response_modalities=["AUDIO"],  # Essential for voice output

            # Include speech_config if needed (using default here)
            speech_config=genai_types.SpeechConfig(
                # Optional: configure voice, language, etc.
            ),

            # Include system_instruction
            system_instruction=genai_types.Content(
                parts=[
                    genai_types.Part(
                        text=(
                            "You are Samarth’s AI assistant. Be friendly, funny, and helpful. "
                            "Speak naturally, use filler words like 'uh', 'like', and brief pauses for realism. "
                        )
                    )
                ]
            ),

            # Optional: Enable session resumption / context compression if needed
            # session_resumption=genai_types.SessionResumptionConfig(),
            # context_window_compression=genai_types.ContextWindowCompressionConfig(
            #      sliding_window=genai_types.SlidingWindow()
            # )
        )
        logger.info(f"[{stream_sid}] Attempting to connect with LiveConnectConfig: {config}")

        async with genai_client.aio.live.connect(model=GEMINI_MODEL, config=config) as session:
            gemini_session = session
            logger.info(f"[{stream_sid}] Successfully connected to Gemini Live API.")
                    # ... rest of the function ...

            logger.info(f"[{stream_sid}] Successfully connected to Gemini Live API.")

            # Run tasks concurrently: one listens to Twilio, one listens to Gemini
            twilio_task = asyncio.create_task(handle_twilio_to_gemini(websocket, gemini_session, stream_sid))
            gemini_task = asyncio.create_task(handle_gemini_to_twilio(gemini_session, websocket, stream_sid))

            # Wait for either task to complete (e.g., due to disconnect or error)
            done, pending = await asyncio.wait(
                [twilio_task, gemini_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel pending tasks to ensure clean shutdown
            for task in pending:
                logger.info(f"[{stream_sid}] Cancelling pending task...")
                task.cancel()
                try:
                    await task # Wait for cancellation (or exception)
                except asyncio.CancelledError:
                    logger.info(f"[{stream_sid}] Task successfully cancelled.")
                except Exception as e:
                    logger.error(f"[{stream_sid}] Error during task cancellation/cleanup: {e}")

            logger.info(f"[{stream_sid}] One of the handlers finished. Done set: {len(done)}")
            # Log any exceptions from the completed tasks
            for task in done:
                try:
                    task.result() # Raise exception if task failed
                except Exception as e:
                    logger.error(f"[{stream_sid}] Task completed with error: {e}", exc_info=False) # Set True for full traceback


    except WebSocketDisconnect:
        logger.info(f"[{stream_sid or 'Unknown SID'}] Twilio WebSocket disconnected during setup or main loop.")
    except ClientError as e:
         logger.error(f"[{stream_sid or 'Unknown SID'}] Gemini API client error during connection: {e}", exc_info=True)
         if websocket.client_state != WebSocketState.DISCONNECTED:
             await websocket.close(code=1011, reason="Gemini Connection Error")
    except Exception as e:
        logger.error(f"[{stream_sid or 'Unknown SID'}] Error in media stream handler: {e}", exc_info=True)
        if websocket.client_state != WebSocketState.DISCONNECTED:
            await websocket.close(code=1011, reason="Internal Server Error") # Internal error
    finally:
        logger.info(f"[{stream_sid or 'Unknown SID'}] Cleaning up WebSocket connection.")
        # Ensure SID mapping is cleaned up if connection drops unexpectedly
        if websocket in twilio_stream_sids:
            del twilio_stream_sids[websocket]
        # The 'async with' context manager for gemini_session should handle its closure.


if __name__ == "__main__":
    import uvicorn
    from websockets.exceptions import ConnectionClosedOK
    from fastapi.websockets import WebSocketState # Import needed for finally block check

    if not GEMINI_API_KEY:
         logger.warning(" démarrage sans GEMINI_API_KEY. Le client GenAI peut ne pas fonctionner.")
         # Consider exiting if API key is strictly required: sys.exit("GEMINI_API_KEY not set.")

    logger.info(f">>> Starting Gemini Live API proxy server on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)