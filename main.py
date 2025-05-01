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
    return JSONResponse(content={"message": "Twilio IVA Server running with Gemini Live API"})

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def incoming_call(request: Request):
    host = request.url.hostname
    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{host}/media-stream")
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()

    # Keep stream_sid in the outer scope so both generator and loop can see it
    stream_sid = None

    # Initialize Gemini client and config
    client = genai.Client(api_key=GEMINI_API_KEY)
    config = types.LiveConnectConfig(
        system_instruction=types.Content(parts=[types.Part(text="""
You are Samarth’s personal assistant...
                """.strip())]),
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE)
            )
        )
    )

    # Generator to pull in Twilio mu-law audio, convert to PCM
    async def twilio_audio_stream():
        nonlocal stream_sid
        try:
            while True:
                msg = await websocket.receive_text()
                data = json.loads(msg)
                event = data.get("event")
                if event == "start":
                    stream_sid = data["start"]["streamSid"]
                elif event == "media":
                    ulaw = base64.b64decode(data["media"]["payload"])
                    pcm = audioop.ulaw2lin(ulaw, 2)
                    yield pcm
                elif event == "stop":
                    break
        except WebSocketDisconnect:
            pass

    async with client.aio.live.connect(model=MODEL, config=config) as session:
        # Inject dummy “Hi” so Gemini speaks first
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text="Hi")]),
            turn_complete=True
        )

        try:
            # Stream real audio in, relay Gemini’s audio back
            async for response in session.start_stream(
                stream=twilio_audio_stream(),
                mime_type="audio/pcm"
            ):
                if getattr(response, "data", None):
                    pcm_out: bytes = response.data
                    # Downsample & μ-law encode
                    pcm8k, _ = audioop.ratecv(pcm_out, 2, 1, 24000, 8000, None)
                    mulaw = audioop.lin2ulaw(pcm8k, 2)
                    payload = base64.b64encode(mulaw).decode("utf-8")

                    # send back on the same streamSid
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
    uvicorn.run(app, host="0.0.0.0", port=PORT)
