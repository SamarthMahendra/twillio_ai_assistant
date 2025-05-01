import os
import json
import asyncio
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from dotenv import load_dotenv
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleRequest
from twilio.twiml.voice_response import VoiceResponse, Connect

load_dotenv()

PORT = int(os.getenv('PORT', 5050))
GEMINI_HOST = "us-central1-aiplatform.googleapis.com"
GEMINI_SERVICE_URL = f"wss://{GEMINI_HOST}/ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent"

app = FastAPI()

# Global credential cache
credential_cache = {
    "creds": None,
    "token": None,
    "expiry": None
}

def get_fresh_bearer_token():
    service_account_info = json.loads(os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"))
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]

    if credential_cache["creds"] is None:
        creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
        creds.refresh(GoogleRequest())
        credential_cache["creds"] = creds
        credential_cache["token"] = creds.token
        credential_cache["expiry"] = creds.expiry
    else:
        creds = credential_cache["creds"]
        if creds.expired:
            creds.refresh(GoogleRequest())
            credential_cache["token"] = creds.token
            credential_cache["expiry"] = creds.expiry

    return credential_cache["token"]

@app.get("/", response_class=JSONResponse)
async def index_page():
    return {"message": "Gemini Proxy Server is running!"}

@app.get("/token")
async def get_bearer_token():
    try:
        token = get_fresh_bearer_token()
        return {"bearer_token": token}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):

    host = request.url.hostname
    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream')
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    await websocket.accept()

    try:
        auth_msg = await websocket.receive_text()
        auth_data = json.loads(auth_msg)
        bearer_token = auth_data.get("bearer_token", None)
    except:
        bearer_token = None

    if not bearer_token:
        bearer_token = get_fresh_bearer_token()

    await start_gemini_proxy(websocket, bearer_token)

async def proxy_task(from_ws, to_ws):
    try:
        async for message in from_ws:
            await to_ws.send(message)
    except Exception as e:
        print(f"Proxy error: {e}")

async def start_gemini_proxy(client_ws: WebSocket, bearer_token: str):
    service_account_info = json.loads(os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"))
    project_id = service_account_info["project_id"]

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
    }

    async with websockets.connect(GEMINI_SERVICE_URL, extra_headers=headers) as gemini_ws:
        # Send setup message
        setup_message = {
            "setup": {
                "model": f"projects/{project_id}/locations/us-central1/publishers/google/models/gemini-1.5-pro-preview-0409",
                "generation_config": {
                    "response_modalities": ["AUDIO"]
                },
                "system_instruction": {
                    "parts": [{
                        "text": (
                            "You are Samarth’s AI assistant. Be friendly, funny, and helpful. "
                            "Speak naturally, use filler words like 'uh', 'like', and brief pauses for realism. "
                            "Use a Boston accent when possible."
                        )
                    }]
                }
            }
        }

        await gemini_ws.send(json.dumps(setup_message))
        await asyncio.gather(
            proxy_task(client_ws, gemini_ws),
            proxy_task(gemini_ws, client_ws)
        )

if __name__ == "__main__":
    import uvicorn
    print(f">>> Starting Gemini proxy server on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
