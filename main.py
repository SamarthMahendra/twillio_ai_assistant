import os
import json
import asyncio
import base64
import audioop
import logging
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect, WebSocketState # Ensure WebSocketState is imported
from dotenv import load_dotenv
from twilio.twiml.voice_response import VoiceResponse, Connect
from google.genai import Client as GenAIClient
from google.genai import types as genai_types
from google.api_core.exceptions import ClientError
from pydantic_core import ValidationError # Import for specific error handling

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
# *** Use a model compatible with the Live API ***
GEMINI_MODEL = os.getenv('GEMINI_MODEL', "gemini-2.0-flash-live-001") # CORRECTED DEFAULT MODEL
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY environment variable not set.")
    # raise ValueError("GEMINI_API_KEY must be set") # Uncomment to enforce

# --- FastAPI App ---
app = FastAPI()

# --- Google GenAI Client ---
try:
    genai_client = GenAIClient(api_key=GEMINI_API_KEY)
    logger.info("Google GenAI Client initialized successfully.")
except Exception as e:
    logger.error(f"Failed to initialize Google GenAI Client: {e}")
    genai_client = None

# --- Audio Conversion Functions ---
def pcm_to_ulaw(pcm_data: bytes, sample_rate: int, target_rate: int = TWILIO_SAMPLE_RATE) -> bytes:
    """Converts 16-bit PCM audio to 8-bit µ-law, handling potential rate conversion."""
    try:
        # Ensure input is bytes
        if not isinstance(pcm_data, bytes):
            logger.warning(f"pcm_to_ulaw received non-bytes input: {type(pcm_data)}")
            return b""

        # Resample if necessary
        if sample_rate != target_rate:
            # state=None is crucial for independent chunk processing
            pcm_data, _ = audioop.ratecv(pcm_data, 2, 1, sample_rate, target_rate, None)

        # Convert linear PCM to µ-law
        ulaw_data = audioop.lin2ulaw(pcm_data, 2)
        return ulaw_data
    except audioop.error as e:
        logger.error(f"Audioop error during PCM ({sample_rate}Hz) to µ-law ({target_rate}Hz) conversion: {e}")
        return b"" # Return empty bytes on error
    except Exception as e:
        logger.error(f"Unexpected error in pcm_to_ulaw: {e}")
        return b""

def ulaw_to_pcm(ulaw_data: bytes, sample_rate: int = TWILIO_SAMPLE_RATE, target_rate: int = GEMINI_INPUT_SAMPLE_RATE) -> bytes:
    """Converts 8-bit µ-law audio to 16-bit PCM, handling potential rate conversion."""
    try:
        # Ensure input is bytes
        if not isinstance(ulaw_data, bytes):
            logger.warning(f"ulaw_to_pcm received non-bytes input: {type(ulaw_data)}")
            return b""

        # Convert µ-law to 16-bit linear PCM
        pcm_data = audioop.ulaw2lin(ulaw_data, 2)

        # Resample if necessary
        if sample_rate != target_rate:
             # state=None is crucial for independent chunk processing
            pcm_data, _ = audioop.ratecv(pcm_data, 2, 1, sample_rate, target_rate, None)

        return pcm_data
    except audioop.error as e:
        logger.error(f"Audioop error during µ-law ({sample_rate}Hz) to PCM ({target_rate}Hz) conversion: {e}")
        return b"" # Return empty bytes on error
    except Exception as e:
        logger.error(f"Unexpected error in ulaw_to_pcm: {e}")
        return b""

# --- FastAPI Routes ---
@app.get("/", response_class=JSONResponse)
async def index_page():
    return {"message": "Gemini Live API Proxy Server for Twilio is running!"}

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handles incoming Twilio call and responds with TwiML to connect WebSocket."""
    host = request.url.hostname
    if not host:
        logger.error("Could not determine hostname from request.")
        return HTMLResponse(content="Error: Could not determine server hostname.", status_code=500)

    logger.info(f"Incoming call received. Connecting WebSocket to wss://{host}/media-stream")
    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream')
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

# --- WebSocket Handler ---
twilio_stream_sids = {} # Simple in-memory store for stream SIDs

async def handle_twilio_to_gemini(twilio_ws: WebSocket, gemini_session, stream_sid: str):
    """Receives messages from Twilio, converts audio, and sends to Gemini."""
    logger.info(f"[{stream_sid}] Starting Twilio listener task.")
    if not gemini_session:
        logger.error(f"[{stream_sid}] Gemini session is not valid in handle_twilio_to_gemini.")
        return # Cannot proceed without a session

    try:
        while True:
            message = await twilio_ws.receive_text()
            data = json.loads(message)
            event = data.get("event")

            if event == "connected":
                logger.info(f"[{stream_sid}] Twilio stream connected event received.")
            elif event == "start":
                rcvd_stream_sid = data.get("streamSid")
                logger.info(f"[{stream_sid}] Twilio stream started event received: {data}")
                # Update SID mapping if necessary (usually matches initial)
                twilio_stream_sids[twilio_ws] = rcvd_stream_sid
            elif event == "media":
                payload = data.get('media', {}).get('payload')
                if payload:
                    # logger.debug(f"[{stream_sid}] Received media payload.")
                    try:
                        decoded_ulaw = base64.b64decode(payload)
                        pcm_audio = ulaw_to_pcm(decoded_ulaw, TWILIO_SAMPLE_RATE, GEMINI_INPUT_SAMPLE_RATE)
                        if pcm_audio:
                            # Send raw PCM audio bytes using send_realtime_input
                            await gemini_session.send_realtime_input(
                                 audio=genai_types.Blob(data=pcm_audio, mime_type=f"audio/pcm;rate={GEMINI_INPUT_SAMPLE_RATE}")
                            )
                            # logger.debug(f"[{stream_sid}] Sent {len(pcm_audio)} bytes PCM to Gemini.")
                        else:
                            logger.warning(f"[{stream_sid}] PCM conversion resulted in empty bytes.")
                    except base64.binascii.Error as b64_error:
                        logger.error(f"[{stream_sid}] Base64 decode error: {b64_error}")
                    except Exception as conv_error:
                        logger.error(f"[{stream_sid}] Error during audio conversion/sending: {conv_error}", exc_info=True)
                else:
                     logger.warning(f"[{stream_sid}] Received media event with no payload.")

            elif event == "mark":
                mark_name = data.get("mark", {}).get("name")
                logger.debug(f"[{stream_sid}] Received Twilio mark: {mark_name}") # Debug level often sufficient
            elif event == "stop":
                logger.info(f"[{stream_sid}] Twilio stream stopped event received.")
                # Optional: Signal end of audio stream to Gemini if needed by VAD config
                # try:
                #     await gemini_session.send_realtime_input(audio_stream_end=True)
                #     logger.info(f"[{stream_sid}] Signalled audio stream end to Gemini.")
                # except Exception as send_err:
                #     logger.error(f"[{stream_sid}] Error signalling audio stream end: {send_err}")
                break # Exit loop on stop event
            else:
                logger.warning(f"[{stream_sid}] Received unknown Twilio event: {event}, data: {data}")

    except WebSocketDisconnect:
        logger.info(f"[{stream_sid}] Twilio WebSocket disconnected.")
    except json.JSONDecodeError as json_err:
        logger.error(f"[{stream_sid}] Error decoding JSON from Twilio: {json_err}. Message: {message}")
    except Exception as e:
        logger.error(f"[{stream_sid}] Error in Twilio listener: {e}", exc_info=True)
    finally:
        logger.info(f"[{stream_sid}] Twilio listener task finished.")
        if twilio_ws in twilio_stream_sids:
            del twilio_stream_sids[twilio_ws]
        # Let the main handler manage closing the Gemini session

async def handle_gemini_to_twilio(gemini_session, twilio_ws: WebSocket, stream_sid: str):
    """Receives messages from Gemini, converts audio, and sends to Twilio."""
    logger.info(f"[{stream_sid}] Starting Gemini listener task.")
    if not stream_sid:
        logger.error(f"[{stream_sid}] Cannot send audio to Twilio without a stream_sid.")
        return
    if not gemini_session:
        logger.error(f"[{stream_sid}] Gemini session is not valid in handle_gemini_to_twilio.")
        return

    try:
        async for response in gemini_session.receive():
            # Log token usage if available
            if response.usage_metadata:
                logger.info(f"[{stream_sid}] Gemini Token Usage: {response.usage_metadata.total_token_count} total tokens.")

            # Handle potential errors from Gemini
            if hasattr(response, 'error') and response.error:
                 logger.error(f"[{stream_sid}] Received error from Gemini: {response.error}")
                 break # Stop processing on error

            # Extract audio data (check common locations)
            audio_data = None
            if hasattr(response, 'data') and response.data:
                 audio_data = response.data
            elif hasattr(response, 'server_content') and response.server_content:
                 if hasattr(response.server_content, 'model_turn') and response.server_content.model_turn:
                      if response.server_content.model_turn.parts:
                           first_part = response.server_content.model_turn.parts[0]
                           if hasattr(first_part, 'inline_data') and first_part.inline_data:
                                if first_part.inline_data.mime_type.startswith("audio/"):
                                     audio_data = first_part.inline_data.data

            if audio_data:
                # logger.debug(f"[{stream_sid}] Received audio data from Gemini.")
                try:
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
                        # Check Twilio WebSocket state before sending
                        if twilio_ws.client_state == WebSocketState.CONNECTED:
                            await twilio_ws.send_text(json.dumps(twilio_media_message))
                            # logger.debug(f"[{stream_sid}] Sent {len(ulaw_audio)} bytes µ-law to Twilio.")
                        else:
                            logger.warning(f"[{stream_sid}] Twilio WebSocket no longer connected. Cannot send media.")
                            break # Stop trying to send if Twilio disconnected
                    else:
                        logger.warning(f"[{stream_sid}] µ-law conversion resulted in empty bytes.")
                except Exception as conv_error:
                    logger.error(f"[{stream_sid}] Error during audio conversion/sending to Twilio: {conv_error}", exc_info=True)

            # Handle other events like interruptions, generation complete etc.
            if hasattr(response, 'server_content') and response.server_content:
                 if hasattr(response.server_content, 'interrupted') and response.server_content.interrupted is True:
                      logger.info(f"[{stream_sid}] Gemini generation interrupted.")
                 if hasattr(response.server_content, 'generation_complete') and response.server_content.generation_complete is True:
                      logger.info(f"[{stream_sid}] Gemini generation complete.")

            if hasattr(response, 'go_away') and response.go_away:
                 logger.warning(f"[{stream_sid}] Received GoAway from Gemini, connection closing soon: {response.go_away.time_left}s")

    except ClientError as e:
         logger.error(f"[{stream_sid}] Gemini API client error in listener: {e}", exc_info=True)
    except WebSocketDisconnect:
        logger.info(f"[{stream_sid}] Gemini session WebSocket disconnected.")
    except Exception as e:
        logger.error(f"[{stream_sid}] Error in Gemini listener: {e}", exc_info=True)
    finally:
        logger.info(f"[{stream_sid}] Gemini listener task finished.")
        # Ensure Twilio connection is closed if Gemini stops unexpectedly
        if twilio_ws.client_state == WebSocketState.CONNECTED:
             try:
                 await twilio_ws.close(code=1000) # Normal closure
                 logger.info(f"[{stream_sid}] Closed Twilio WebSocket from Gemini handler.")
             except Exception as close_err:
                  logger.error(f"[{stream_sid}] Error closing Twilio WebSocket: {close_err}")

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handles the WebSocket connection from Twilio."""
    await websocket.accept()
    logger.info("Twilio WebSocket client connected.")

    stream_sid = None
    gemini_session = None
    twilio_task = None
    gemini_task = None

    try:
        # --- Wait for the 'start' message to get the streamSid ---
        logger.info("Waiting for Twilio 'start' event...")
        while stream_sid is None:
             message = await websocket.receive_text()
             # logger.debug(f"Received initial message: {message[:100]}...") # Log snippet
             try:
                 data = json.loads(message)
                 event = data.get("event")
                 if event == "start":
                      stream_sid = data.get("streamSid")
                      if stream_sid:
                           twilio_stream_sids[websocket] = stream_sid
                           logger.info(f"[{stream_sid}] Received start event. Stream SID: {stream_sid}")
                           break # Got the SID, proceed
                      else:
                           logger.error("Received start event but no streamSid found.")
                           await websocket.close(code=1003, reason="Missing streamSid") # Unsupported data
                           return
                 elif event == "connected":
                      logger.info("Received connected event. Waiting for start...")
                 else:
                      logger.warning(f"Received unexpected event '{event}' before start. Data: {data}")
             except json.JSONDecodeError as json_err:
                  logger.error(f"Error decoding initial JSON from Twilio: {json_err}. Message: {message}")
                  await websocket.close(code=1003, reason="Invalid JSON received") # Unsupported data
                  return

        if not stream_sid:
             # This should theoretically not be reached if the loop breaks correctly
             logger.error("Failed to obtain streamSid. Closing connection.")
             await websocket.close(code=1011, reason="streamSid not received")
             return

        if not genai_client:
            logger.error(f"[{stream_sid}] GenAI client not initialized. Cannot proceed.")
            await websocket.close(code=1011, reason="Server configuration error")
            return

        # --- Configure and Connect to Gemini Live API ---
        # Use the corrected model name (set via env var or default above)
        logger.info(f"[{stream_sid}] Connecting to Gemini Live API model: {GEMINI_MODEL}")

        # Start with minimal config, then add back others if needed
        config = {
            "response_modalities": ["AUDIO"],
            # Add back other fields AFTER confirming connection works:
            # "speech_config": genai_types.SpeechConfig(),
            # "system_instruction": genai_types.Content(parts=[genai_types.Part(text="...")])
        }
        logger.info(f"[{stream_sid}] Attempting to connect with config: {config}")

        # Use try-except around the connection itself
        try:
            # ExperimentalWarning is expected, handled by SDK
            async with genai_client.aio.live.connect(model=GEMINI_MODEL, config=config) as session:
                gemini_session = session
                logger.info(f"[{stream_sid}] Successfully connected to Gemini Live API.")

                # --- Start Concurrent Tasks ---
                twilio_task = asyncio.create_task(handle_twilio_to_gemini(websocket, gemini_session, stream_sid))
                gemini_task = asyncio.create_task(handle_gemini_to_twilio(gemini_session, websocket, stream_sid))

                # Wait for either task to complete
                done, pending = await asyncio.wait(
                    [twilio_task, gemini_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # --- Task Cleanup ---
                logger.info(f"[{stream_sid}] One handler task completed. Cleaning up...")
                for task in pending:
                    if not task.done():
                        task.cancel()
                        try:
                            await task # Allow cancellation to propagate
                        except asyncio.CancelledError:
                            logger.info(f"[{stream_sid}] Task successfully cancelled.")
                        except Exception as e_cancel:
                             logger.error(f"[{stream_sid}] Error during pending task cancellation: {e_cancel}")

                # Log results/exceptions from completed tasks
                for task in done:
                    try:
                        task.result() # Raise exception if task failed
                        logger.info(f"[{stream_sid}] Completed task finished successfully.")
                    except asyncio.CancelledError:
                         logger.info(f"[{stream_sid}] Completed task was cancelled.") # Should not happen if FIRST_COMPLETED
                    except Exception as e_done:
                        logger.error(f"[{stream_sid}] Completed task finished with error: {e_done}", exc_info=False)

        except ValidationError as e: # Catch Pydantic validation errors specifically
             logger.error(f"[{stream_sid}] Pydantic Validation Error during connect: {e}", exc_info=True)
             await websocket.close(code=1011, reason="Gemini Configuration Error")
             return # Exit function after closing
        except ClientError as e:
             logger.error(f"[{stream_sid}] Gemini API ClientError during connect: {e}", exc_info=True)
             await websocket.close(code=1011, reason="Gemini Connection Error")
             return # Exit function after closing
        except Exception as e: # Catch other potential errors during config/connect
             # This includes the websockets.exceptions.ConnectionClosedError
             logger.error(f"[{stream_sid}] Error during Gemini connection setup: {e}", exc_info=True)
             # Provide a more specific reason if possible based on the error type/message
             reason = "Gemini Connection Setup Error"
             if isinstance(e, ConnectionClosedError) and e.code == 1008:
                  reason = "Model Not Supported or Found"
             await websocket.close(code=1011, reason=reason)
             return # Exit function after closing

    except WebSocketDisconnect:
        logger.info(f"[{stream_sid or 'Unknown SID'}] Twilio WebSocket disconnected during setup or main loop.")
    except Exception as e:
        logger.error(f"[{stream_sid or 'Unknown SID'}] Unexpected error in media stream handler: {e}", exc_info=True)
        # Ensure cleanup even if error happens before tasks start
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close(code=1011, reason="Internal Server Error")
    finally:
        logger.info(f"[{stream_sid or 'Unknown SID'}] Cleaning up WebSocket connection handler.")
        # Cancel tasks if they are still running (e.g., if main handler loop exits unexpectedly)
        if twilio_task and not twilio_task.done():
             twilio_task.cancel()
        if gemini_task and not gemini_task.done():
             gemini_task.cancel()
        # Clean up SID mapping
        if websocket in twilio_stream_sids:
            del twilio_stream_sids[websocket]
        # The 'async with' context manager for gemini_session handles its closure if entered.


if __name__ == "__main__":
    import uvicorn
    # from websockets.exceptions import ConnectionClosedOK # Not explicitly used here

    if not genai_client:
         logger.warning("GenAI client failed to initialize. API calls will fail.")
         # Depending on requirements, might exit here:
         # import sys
         # sys.exit("Exiting due to GenAI client initialization failure.")

    logger.info(f">>> Starting Gemini Live API proxy server on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
