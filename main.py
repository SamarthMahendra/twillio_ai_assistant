import os
import json
import base64
import asyncio
import audioop
import time # Import time for timing
import traceback # Import traceback for detailed errors

from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect
from dotenv import load_dotenv
from google import genai
from google.genai import types

# ... (Keep your existing setup: load_dotenv, API Key, Config, FastAPI app, SYSTEM_INSTRUCTION, etc.) ...

# --- Make sure SPEECH_CONFIG and LIVE_CONNECT_CONFIG are defined correctly ---
SPEECH_CONFIG = types.SpeechConfig(
    voice_config=types.VoiceConfig(
        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE)
    )
)

LIVE_CONNECT_CONFIG = types.LiveConnectConfig(
    system_instruction=SYSTEM_INSTRUCTION,
    response_modalities=["AUDIO"],
    speech_config=SPEECH_CONFIG
)
# --- End common config ---


@app.get("/", response_class=JSONResponse)
async def health_check():
    return JSONResponse(content={"message": "Twilio IVA Server running with Gemini Live API"})

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def incoming_call(request: Request):
    host = request.url.hostname
    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{host}/media-stream")
    response.append(connect)
    print(">>> /incoming-call: Sending TwiML to connect stream.")
    return HTMLResponse(content=str(response), media_type="application/xml")


async def send_audio_to_twilio(websocket: WebSocket, stream_sid: str, pcm_audio: bytes):
    """Helper function to process and send PCM audio to Twilio."""
    if not pcm_audio:
        print("[WARN] send_audio_to_twilio: No audio data to send.")
        return
    if not stream_sid:
        print("[ERROR] send_audio_to_twilio: stream_sid is None. Cannot send.")
        return
    try:
        start_send_time = time.time()
        print(f"[{start_send_time:.2f}] send_audio_to_twilio: Processing {len(pcm_audio)} bytes for stream {stream_sid}...")
        # Assuming Gemini outputs 24kHz mono PCM
        pcm_resampled, _ = audioop.ratecv(pcm_audio, 2, 1, 24000, 8000, None)
        mulaw = audioop.lin2ulaw(pcm_resampled, 2)
        payload = base64.b64encode(mulaw).decode('utf-8')
        print(f"[{time.time():.2f}] send_audio_to_twilio: Sending {len(payload)} base64 chars payload...")
        await websocket.send_json({
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": payload}
        })
        end_send_time = time.time()
        print(f"[{end_send_time:.2f}] send_audio_to_twilio: Send successful. Took {end_send_time - start_send_time:.3f}s")
    except audioop.error as e:
        print(f"[ERROR] send_audio_to_twilio: Audio processing error: {e}")
        traceback.print_exc()
    except Exception as e:
        print(f"[ERROR] send_audio_to_twilio: Failed to send JSON to WebSocket: {e}")
        traceback.print_exc()


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()
    print(f"[{time.time():.2f}] /media-stream: WebSocket accepted.")
    stream_sid = None
    client = None
    session = None

    try:
        # 1. Wait for the 'start' event from Twilio
        print(f"[{time.time():.2f}] /media-stream: Waiting for Twilio start event...")
        while stream_sid is None:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=10.0) # Add timeout
                data = json.loads(msg)
                event = data.get("event")
                print(f"[{time.time():.2f}] /media-stream: Received event '{event}' while waiting for start.")
                if event == "start":
                    stream_sid = data["start"]["streamSid"]
                    print(f"[{time.time():.2f}] /media-stream: Stream started: {stream_sid}")
                elif event == "stop":
                    print(f"[{time.time():.2f}] /media-stream: Stream stopped by Twilio before processing could start.")
                    await websocket.close()
                    return
            except asyncio.TimeoutError:
                print(f"[{time.time():.2f}] /media-stream: Timeout waiting for Twilio start event.")
                await websocket.close()
                return
            except WebSocketDisconnect:
                 print(f"[{time.time():.2f}] /media-stream: WebSocket disconnected while waiting for start.")
                 return # Exit if disconnected

        # 2. Initialize Gemini Client
        print(f"[{time.time():.2f}] /media-stream: Initializing Gemini Client.")
        client = genai.Client(api_key=GEMINI_API_KEY)

        # 3. Generate the initial greeting
        print(f"[{time.time():.2f}] /media-stream: Generating initial greeting from Gemini...")
        initial_audio_pcm = None
        try:
            generation_start_time = time.time()
            greeting_prompt = "Hey! You’ve reached Samarth’s personal assistant. What can I help you with today?" # More direct prompt
            initial_response = await client.generate_content_async(
                contents=[greeting_prompt],
                generation_config=types.GenerationConfig(
                    response_mime_type="audio/pcm"
                ),
                 model=MODEL,
                 request_options={"speech_config": SPEECH_CONFIG}
            )
            generation_end_time = time.time()
            print(f"[{generation_end_time:.2f}] /media-stream: Gemini generation took {generation_end_time - generation_start_time:.3f}s")

            if initial_response.candidates and initial_response.candidates[0].content.parts:
                part = initial_response.candidates[0].content.parts[0]
                if hasattr(part, 'audio_data') and part.audio_data:
                     initial_audio_pcm = part.audio_data
                     print(f"[{time.time():.2f}] /media-stream: Generated initial greeting audio ({len(initial_audio_pcm)} bytes).")
                     # 4. Send the initial greeting audio to Twilio
                     await send_audio_to_twilio(websocket, stream_sid, initial_audio_pcm)
                else:
                    print("[WARN] /media-stream: Gemini response part did not contain audio data.")
            else:
                print("[WARN] /media-stream: Gemini did not return valid candidates/parts for the initial greeting.")

        except Exception as e:
            print(f"[ERROR] /media-stream: Failed during initial greeting generation or sending: {e}")
            traceback.print_exc() # Print full traceback


        # 5. Start the main streaming interaction loop
        print(f"[{time.time():.2f}] /media-stream: Starting Gemini live connection for conversation...")
        async with client.aio.live.connect(model=MODEL, config=LIVE_CONNECT_CONFIG) as session:
            print(f"[{time.time():.2f}] /media-stream: Gemini live session connected.")
            # Generator to yield PCM audio from Twilio
            async def twilio_audio_stream_post_greeting():
                try:
                    while True:
                        msg = await websocket.receive_text()
                        data = json.loads(msg)
                        event = data.get("event")
                        if event == "media":
                            # Don't process media if stream_sid isn't set (shouldn't happen here, but safe)
                            if not stream_sid:
                                continue
                            # print(f"[{time.time():.2f}] Received Twilio media chunk") # Verbose logging if needed
                            ulaw = base64.b64decode(data["media"]["payload"])
                            pcm = audioop.ulaw2lin(ulaw, 2)
                            yield pcm
                        elif event == "stop":
                            print(f"[{time.time():.2f}] /media-stream: Stream stopped by Twilio during conversation.")
                            break
                        elif event == "mark":
                             print(f"[{time.time():.2f}] /media-stream: Received mark: {data.get('mark', {}).get('name')}")
                        # Ignore 'start' event if received again
                except WebSocketDisconnect:
                    print(f"[{time.time():.2f}] /media-stream: Twilio WebSocket disconnected during conversation.")
                except Exception as gen_e:
                     print(f"[ERROR] /media-stream: Error in twilio_audio_stream_post_greeting: {gen_e}")
                     traceback.print_exc()
                finally:
                    print(f"[{time.time():.2f}] /media-stream: Audio stream generator finished.")

            # Stream subsequent audio to Gemini and receive responses
            print(f"[{time.time():.2f}] /media-stream: Starting session.start_stream loop...")
            async for response in session.start_stream(stream=twilio_audio_stream_post_greeting(), mime_type="audio/pcm"):
                # print(f"[{time.time():.2f}] Received response chunk from Gemini") # Verbose
                if hasattr(response, 'data') and response.data:
                    # print(f"[{time.time():.2f}] Gemini response has audio data ({len(response.data)} bytes)") # Verbose
                    await send_audio_to_twilio(websocket, stream_sid, response.data)
                # else:
                    # print(f"[{time.time():.2f}] Gemini response chunk has no audio data") # Verbose

    except WebSocketDisconnect:
        print(f"[{time.time():.2f}] /media-stream: WebSocket disconnected (outer scope).")
    except Exception as e:
        print(f"[ERROR] /media-stream: Unhandled error in main handler: {e}")
        traceback.print_exc()
    finally:
        print(f"[{time.time():.2f}] /media-stream: Cleaning up...")
        # Ensure WebSocket is closed
        try:
            if websocket.client_state == websocket.client_state.CONNECTED:
                 await websocket.close()
                 print(f"[{time.time():.2f}] /media-stream: WebSocket closed.")
        except Exception as close_e:
            print(f"[{time.time():.2f}] /media-stream: Error closing WebSocket: {close_e}")

if __name__ == "__main__":
    import uvicorn
    print(f"Starting server on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)