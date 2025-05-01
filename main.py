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

    # ----------------------------------------------------------------
    # 1) Twilio will first send a "connected" event, then a "start".
    #    Loop until we see "start", then stash streamSid.
    # ----------------------------------------------------------------
    stream_sid = None
    while True:
        raw = await websocket.receive_text()
        msg = json.loads(raw)
        event = msg.get("event")

        if event == "start":
            stream_sid = msg["start"]["streamSid"]
            print(f"[Twilio] Stream started: {stream_sid}")
            break
        else:
            # ignore anything else (e.g. "connected")
            continue

    # ----------------------------------------------------------------
    # 2) Init Gemini client & config
    # ----------------------------------------------------------------
    client = genai.Client(api_key=GEMINI_API_KEY)
    config = types.LiveConnectConfig(
        system_instruction=types.Content(
            parts=[types.Part(text="""
                You are Samarth’s personal assistant who chats like over coffee,
                using fillers (“um,” “uh,” “y’know”), pauses (“…”), and a chill tone.
                If you don’t know something, say “Hmm… not sure, but lemme think.”
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
        # First turn: prompt Gemini
        prompt = "Hello? Gemini, are you there?"
        await session.send_client_content(
            turns={"role": "user", "parts": [{"text": prompt}]},
            turn_complete=True
        )
        print(f"[Gemini] Sent prompt: {prompt}")

        # Wait for Gemini’s first audio chunk and immediately forward it
        async for chunk in session.receive():
            if getattr(chunk, "data", None):
                encoded = base64.b64encode(chunk.data).decode("utf-8")
                await websocket.send_json({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": encoded}
                })
                break

    async def twilio_audio_stream():
        # Generator: receive Twilio→yield PCM to Gemini
        try:
            while True:
                raw = await websocket.receive_text()
                msg = json.loads(raw)
                evt = msg.get("event")

                if evt == "media":
                    ulaw = base64.b64decode(msg["media"]["payload"])
                    pcm = audioop.ulaw2lin(ulaw, 2)
                    yield pcm

                elif evt == "stop":
                    print("[Twilio] Stream stopped by Twilio")
                    break
        except WebSocketDisconnect:
            print("[Twilio] WebSocket disconnected")

    # ----------------------------------------------------------------
    # 3) Open Live API session, speak first, then relay
    # ----------------------------------------------------------------
    async with client.aio.live.connect(model=MODEL, config=config) as session:
        # Gemini speaks into the call before any user audio
        await say_hello(session)

        # Now pipe the rest of the call bi-directionally
        async for resp in session.start_stream(
            stream=twilio_audio_stream(),
            mime_type="audio/pcm"
        ):
            if getattr(resp, "data", None):
                # downsample 24k→8k, convert to μ-law, forward to Twilio
                pcm_out = resp.data
                pcm_rs, _ = audioop.ratecv(pcm_out, 2, 1, 24000, 8000, None)
                ulaw = audioop.lin2ulaw(pcm_rs, 2)
                payload = base64.b64encode(ulaw).decode("utf-8")

                await websocket.send_json({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": payload}
                })

    # Clean up
    await websocket.close()


if __name__ == "__main__":
    import uvicorn
    print(f"Starting on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
