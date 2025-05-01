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

# Load Gemini API key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("Missing Gemini API key. Set GEMINI_API_KEY in .env")

# Configuration
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

    # 1️⃣ Pull off Twilio's "start" to grab streamSid immediately
    msg = await websocket.receive_text()
    data = json.loads(msg)
    if data.get("event") != "start":
        raise RuntimeError("Expected Twilio 'start' event first")
    stream_sid = data["start"]["streamSid"]
    print(f"Stream started: {stream_sid}")

    # Initialize Gemini client & config
    client = genai.Client(api_key=GEMINI_API_KEY)
    config = types.LiveConnectConfig(
        system_instruction=types.Content(
            parts=[types.Part(text="""
                You are Samarth’s personal assistant who usually talks to recruiters or anyone interested
                in hiring him. When you speak, use natural fillers (“um,” “uh,” “y’know,” “I mean,” “like”),
                insert brief pauses (“…”), and keep a chill, conversational tone. If you don’t know something,
                say “Hmm… not sure, but lemme think.”
            """)]
        ),
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE)
            )
        )
    )

    async def say_hello(session):
        # Send the initial prompt
        message = "Hello? Gemini, are you there?"
        await session.send_client_content(
            turns={"role": "user", "parts": [{"text": message}]},
            turn_complete=True
        )
        print(f"Sent message: {message}")

        # Wait for the first audio chunk back from Gemini, then send it to Twilio
        async for chunk in session.receive():
            if getattr(chunk, "data", None):
                mulaw_payload = base64.b64encode(chunk.data).decode("utf-8")
                await websocket.send_json({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": mulaw_payload}
                })
                break  # only send the first response here

    async def twilio_audio_stream():
        # Generator: Twilio → Gemini
        try:
            while True:
                msg = await websocket.receive_text()
                data = json.loads(msg)
                event = data.get("event")
                if event == "media":
                    ulaw = base64.b64decode(data["media"]["payload"])
                    pcm = audioop.ulaw2lin(ulaw, 2)
                    yield pcm
                elif event == "stop":
                    print("Stream stopped by Twilio")
                    break
        except WebSocketDisconnect:
            print("Twilio WebSocket disconnected in stream generator")

    # 2️⃣ Open Gemini Live session, speak first, then relay
    async with client.aio.live.connect(model=MODEL, config=config) as session:
        # Gemini says hello into the call
        await say_hello(session)

        # Then pipe any further audio back-and-forth
        async for response in session.start_stream(
            stream=twilio_audio_stream(),
            mime_type="audio/pcm"
        ):
            if getattr(response, "data", None):
                # downsample from 24k→8k and convert to μ-law
                pcm_out = response.data
                pcm_resampled, _ = audioop.ratecv(pcm_out, 2, 1, 24000, 8000, None)
                mulaw = audioop.lin2ulaw(pcm_resampled, 2)
                payload = base64.b64encode(mulaw).decode("utf-8")

                await websocket.send_json({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": payload}
                })

    # When we exit the `async with`, the Gemini session is automatically closed
    await websocket.close()


if __name__ == "__main__":
    import uvicorn
    print(f"Starting server on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
