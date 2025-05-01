import os
import json
import base64
import asyncio
import audioop

from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("Missing Gemini API key. Set GEMINI_API_KEY in .env")

MODEL = os.getenv("MODEL", "gemini-2.0-flash-live-001")
VOICE = os.getenv("VOICE", "Leda")
PORT = int(os.getenv("PORT", 5050))

app = FastAPI()

@app.get("/", response_class=JSONResponse)
async def health_check():
    return JSONResponse({"message": "Twilio IVA Server running with Gemini Live API"})

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def incoming_call(request: Request):
    host = request.url.hostname
    resp = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{host}/media-stream")
    resp.append(connect)
    return HTMLResponse(str(resp), media_type="application/xml")


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()

    # Initialize Gemini client
    client = genai.Client(api_key=GEMINI_API_KEY)
    config = types.LiveConnectConfig(
        system_instruction=types.Content(
            parts=[
                types.Part(
                    text="""
                    You are a helpful AI assistant. Greet the caller warmly and ask how you can help them today.
                    """
                )
            ]
        ),
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE)
            )
        )
    )
    stream_sid = None

    # Wait for Twilio to establish the stream and get stream SID
    try:
        while stream_sid is None:
            msg = await websocket.receive_text()
            data = json.loads(msg)
            if data.get("event") == "start":
                stream_sid = data["start"]["streamSid"]
                print(f"Stream started: {stream_sid}")
                break
    except Exception as e:
        print(f"Error during stream initialization: {e}")
        await websocket.close()
        return

    # Generator to yield PCM audio from Twilio mu-law stream
    async def twilio_audio_stream():
        nonlocal stream_sid
        try:
            while True:
                msg = await websocket.receive_text()
                data = json.loads(msg)
                event = data.get("event")
                if event == "media":
                    ulaw = base64.b64decode(data["media"]["payload"])
                    # Convert from mu-law to 16-bit PCM
                    pcm = audioop.ulaw2lin(ulaw, 2)
                    yield pcm
                elif event == "stop":
                    print("Stream stopped by Twilio")
                    break
        except WebSocketDisconnect:
            print("Twilio WebSocket disconnected in stream generator")

    async with client.aio.live.connect(model=MODEL, config=config) as session:
        try:
            # Make Gemini speak first by sending an initial message
            await session.send_client_content(
                turns={"role": "user", "parts": [{"text": "Hello, please introduce yourself to the caller."}]},
                turn_complete=True
            )

            # First, process the initial greeting response
            async for response in session.receive():
                if getattr(response, 'data', None):
                    pcm_out = response.data
                    # Downsample and convert PCM to mu-law for Twilio
                    pcm_resampled, _ = audioop.ratecv(pcm_out, 2, 1, 24000, 8000, None)
                    mulaw = audioop.lin2ulaw(pcm_resampled, 2)
                    payload = base64.b64encode(mulaw).decode('utf-8')
                    await websocket.send_json({
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": payload}
                    })

                # Break out of this loop when the initial greeting is complete
                if hasattr(response, 'server_content') and getattr(response.server_content, 'generation_complete',
                                                                   False):
                    break

            # Then continue with the regular conversation stream
            async for response in session.start_stream(stream=twilio_audio_stream(),
                                                       mime_type="audio/pcm"):  # type: ignore
                if getattr(response, 'data', None):
                    pcm_out = response.data
                    # Downsample and convert PCM to mu-law for Twilio
                    pcm_resampled, _ = audioop.ratecv(pcm_out, 2, 1, 24000, 8000, None)
                    mulaw = audioop.lin2ulaw(pcm_resampled, 2)
                    payload = base64.b64encode(mulaw).decode('utf-8')
                    await websocket.send_json({
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": payload}
                    })
        except Exception as e:
            print(f"[ERROR] gemini_websocket: {e}")
        finally:
            await websocket.close()
            await session.aclose()


if __name__ == "__main__":
    import uvicorn
    print(f"Starting on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
