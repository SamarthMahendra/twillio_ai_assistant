import os
import json
import base64
import asyncio

from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# Load Gemini API key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("Missing Gemini API key. Set GEMINI_API_KEY in .env")

# Configuration
model = os.getenv("MODEL", "gemini-2.0-flash-live-001")
VOICE = os.getenv("VOICE", "Kore")
PORT = int(os.getenv("PORT", 5050))

app = FastAPI()

@app.get("/", response_class=JSONResponse)
async def health_check():
    # Health check endpoint returns JSON
    return JSONResponse(content={"message": "Twilio Media Stream Server running with Gemini Live API"})

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def incoming_call(request: Request):
    # Respond with TwiML to connect the call to our media-stream endpoint
    host = request.url.hostname
    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{host}/media-stream")
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()

    # Initialize Gemini Live API client
    client = genai.Client(api_key=GEMINI_API_KEY)
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE)
            )
        )
    )

    async with client.aio.live.connect(model=model, config=config) as session:
        stream_sid = None

        async def recv_twilio():
            nonlocal stream_sid
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    event = data.get("event")
                    if event == "start":
                        stream_sid = data["start"]["streamSid"]
                        print(f"Stream started: {stream_sid}")
                    elif event == "media":
                        payload = data["media"]["payload"]
                        raw = base64.b64decode(payload)
                        # Send incoming audio to Gemini Live as real-time input
                        await session.send(
                            input=types.LiveSendRealtimeInputParameters(
                                audio=types.Blob(data=raw, mime_type="audio/x-ulaw;rate=8000")
                            ),
                            end_of_turn=False,
                        )
            except WebSocketDisconnect:
                print("Twilio WebSocket disconnected, closing Gemini session.")
                await session.aclose()

        async def send_responses():
            try:
                async for resp in session.receive():
                    # Forward Gemini audio output back to Twilio
                    if getattr(resp, 'data', None) is not None:
                        encoded = base64.b64encode(resp.data).decode()
                        await websocket.send_json({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": encoded}
                        })
            except Exception as e:
                print(f"[ERROR] send_responses: {e}")

        await asyncio.gather(recv_twilio(), send_responses())

if __name__ == "__main__":
    import uvicorn
    print(f"Starting server on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
