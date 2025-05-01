# -*- coding: utf-8 -*-
import os
import json
import base64
import asyncio
import audioop
import time # Import time for timing
import traceback # Import traceback for detailed errors
import wave
import typing # <--- Added import for typing.Any

from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.generativeai.types import ModelServiceClient, LiveConnectRequest # Import specific types

load_dotenv()

# Load Gemini API key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("Missing Gemini API key. Set GEMINI_API_KEY in .env")

# Configuration
MODEL = os.getenv("MODEL", "models/gemini-1.5-flash-latest") # Use a model known to support LiveConnect well
VOICE = os.getenv("VOICE", "Leda") # Reverted to original example voice name from your first snippet
PORT = int(os.getenv("PORT", 5050))
app = FastAPI()

# --- Define the common Gemini Config parts ---
SYSTEM_INSTRUCTION = types.Content(parts=
[types.Part(
text="""You are Samarth personal assistant who usually talks to recruiters or anyone who is interested in samarth's profile or would want to hire him. :
Samarth's info:
MARASANIGE SAMARTH MAHENDRA | Phone: +1 (857) 707-1671 | Email: samarth.mahendragowda@gmail.com | Location: Boston, MA, USA | LinkedIn | GitHub
EDUCATION:
Northeastern University, Boston, MA — Master’s in Computer Science (Jan 2024 – Dec 2025). Relevant coursework: Programming Design Paradigm, Database Management Systems, Algorithms, Natural Language Processing, Machine Learning, Foundation of Software Engineering, Mobile App Development.
Dayananda Sagar College of Engineering, Bengaluru, India — Bachelor’s in Computer Science (Aug 2018 – Jul 2022).
SKILLS:
Languages: Python, Java, C/C++, JavaScript, TypeScript, NoSQL
Frameworks/Libraries: Django REST Framework, Flask, React.js
Databases: PostgreSQL, Redis, MongoDB, Elasticsearch, ChromaDB
Cloud/DevOps: AWS, Terraform, Docker, Kubernetes, Prometheus, Datadog, Celery
Tools/Platforms: Git, Linux/Unix, Puppeteer, LLM Integration
Concepts: Microservices, Data Modeling, REST APIs, System Design, Distributed Systems, Problem Solving
PROFESSIONAL EXPERIENCE:
Draup, Bengaluru, India — Associate Software Development Engineer (Aug 2022 – Nov 2023):
Maintained core platform features (digital tech stack, outsourcing, customer, and university pages).
Designed internal dynamic query generation framework for real-time aggregation, improving chatbot performance by 60% and reducing entity development time by 80%.
Revamped filters with logical operator flexibility and nested filtering (e.g., "(a AND b) OR c").
Built 100+ modular Python/Django APIs across platform services.
Implemented subscription-based access control system.
Migrated APIs from PostgreSQL to Elasticsearch for real-time aggregation—achieved 5× faster response time.
Used query optimization (partitioning, restructuring, indexing, views) to improve execution by 400% and reduce ops cost by 50%.
Monitored platform health with Datadog and AWS CloudWatch, reducing downtime from 4% to 1% and improving issue resolution by 75%.
Draup, Bengaluru, India — Associate Software Development Engineer Intern (Apr 2022 – Jun 2022):
Debugged APIs using Datadog, reducing issue resolution time by 30%.
Added image caching, reducing image load times by 70%.
Wrote automated DB cleanup scripts to improve efficiency by 25%.
PROJECTS & OUTSIDE EXPERIENCE:
Open Jobs - Analytics (Dec 2024 – Present), Boston, MA:
Inspired by Levels.fyi; aggregates 500+ job postings.
Built producer-consumer system with Celery, monitored via Prometheus and Grafana (99.9% uptime).
Used Playwright & Puppeteer to scrape 1000+ daily data points.
Developed Python reverse proxy with router port-forwarding, reducing latency by 40%.
Automated HTML/CSS selector extraction using LLMs, onboarding new companies 90% faster.
LinkedIn Assist (LLM-powered Bot) (Remote):
Built Chrome extension (Flask backend via CodeSandbox) to filter LinkedIn jobs using natural language prompts.
Used GPT-3.5 for entity extraction and boolean query support (AND, OR, NOT), mimicking LinkedIn filters.
Myocardium Wall Motion & Thickness Map (Patent Pending) — App No: 202341086278 (India), Bengaluru (Nov 2021 – Sep 2023):
Mapped cine-series MRI scans for heart wall motion, fibrosis, and thickness during systole/diastole.
Used custom algorithms for wall thickness and ambiguous zone measurements, improving precision by 50%.
Parallelized with NumPy and multiprocessing, achieving 60× faster execution.
Bike Rental System (Feb 2024 – Apr 2024), Boston, MA:
Built full-stack system (React.js, Django, MySQL) deployed on Azure, Digital Ocean, Netlify.
Added Redis caching and Datadog monitoring.
Used JWT for secure login and protected resources.
Stock Market Simulation App (Feb 2024 – Apr 2024), Boston, MA:
Java MVC system managing stock investments with buy/sell tracking.
Integrated APIs and data visualization (line/bar charts, moving averages, gain/loss trends).
StackOverflow Clone (Feb 2025 – Apr 2025):
Full-stack Q&A platform with React frontend and Node.js/Express backend using TypeScript.
Followed MVC architecture; used Facade, Strategy, Validator, Factory patterns.
Built end-to-end & integration tests using Jest and Cypress.
Modern responsive UI with React Context and theme support.
Skills: TypeScript, JavaScript, React.js, Node.js, MongoDB, Cypress, Jest, CodeQL, DevOps, Full-stack.
Intelligent Agent System with Multi-LLM Integration (Apr 2025):
Integrated OpenAI GPT-4 and Google Gemini with custom tools.
Real-time communication via FastAPI WebSockets and Discord.
Mongoose/MongoDB for persistent tool-call records.
GitHub: Project Repox
Portfolio: https://github.com/SamarthMahendra/samarthmahendra.github.io

When you speak, do the following:
1. Use natural “stop words” and fillers: “um,” “uh,” “y’know,” “I mean,” “like.”
2. Insert brief pauses for realism, marked by “…” or commas:
3. Imagine you're chatting with someone over coffee. You’re super chill, but sharp. If you don’t know something, say it like “Hmm… not sure, but lemme think."""
)]
)

# --- Reverted to original SPEECH_CONFIG and LIVE_CONNECT_CONFIG ---
# --- WARNING: These configurations may lead to audio format mismatches ---
SPEECH_CONFIG = types.SpeechConfig(
    voice_config=types.VoiceConfig(
        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE) # Using original structure
    )
)

LIVE_CONNECT_CONFIG = types.LiveConnectConfig(
    system_instruction=SYSTEM_INSTRUCTION,
    response_modalities=["AUDIO"],
    speech_config=SPEECH_CONFIG
    # NOTE: Missing audio_input_config here compared to the recommended version.
    # This may cause Gemini to misinterpret incoming audio.
)
# --- End original config ---

# Global flag to signal disconnection
disconnect_signal = asyncio.Event()

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

async def send_audio_to_twilio(websocket: WebSocket, stream_sid: str, audio_from_gemini: bytes):
    """
    Helper function to process audio from Gemini and send to Twilio.
    *** WARNING: This function EXPECTS 24kHz linear16 PCM input from Gemini. ***
    *** The original SPEECH_CONFIG does NOT guarantee this format. This may cause errors. ***
    """
    if not audio_from_gemini:
        print("[WARN] send_audio_to_twilio: No audio data to send.")
        return
    if not stream_sid:
        print("[ERROR] send_audio_to_twilio: stream_sid is None. Cannot send.")
        return
    if disconnect_signal.is_set():
        print(f"[INFO] send_audio_to_twilio: Disconnect signaled, skipping send for stream {stream_sid}.")
        return

    try:
        start_send_time = time.time()
        # print(f"[{start_send_time:.2f}] send_audio_to_twilio: Processing {len(audio_from_gemini)} bytes from Gemini for stream {stream_sid}...")

        # ***** Potential Failure Point *****
        # This assumes audio_from_gemini is 24kHz linear16 PCM.
        # If Gemini sends a different format (e.g., mulaw, opus) due to the original config,
        # the following audioop calls will likely fail.
        try:
            # Attempt to convert 24kHz linear16 -> 8kHz linear16 -> 8kHz mulaw
            pcm_resampled_8khz, _ = audioop.ratecv(audio_from_gemini, 2, 1, 24000, 8000, None)
            mulaw = audioop.lin2ulaw(pcm_resampled_8khz, 2)
        except audioop.error as audio_err:
             print(f"[FATAL ERROR] send_audio_to_twilio: Audio processing failed! Input format from Gemini might be incorrect due to original SPEECH_CONFIG. Error: {audio_err}")
             traceback.print_exc()
             # Cannot proceed if format is wrong. Signal disconnect.
             disconnect_signal.set()
             return # Stop trying to send corrupt data

        payload = base64.b64encode(mulaw).decode('utf-8')
        # print(f"[{time.time():.2f}] send_audio_to_twilio: Sending {len(payload)} base64 chars (8kHz mulaw) payload...")

        await websocket.send_json({
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": payload}
        })
        end_send_time = time.time()
        # print(f"[{end_send_time:.2f}] send_audio_to_twilio: Send successful. Took {end_send_time - start_send_time:.3f}s")

    except WebSocketDisconnect:
         print(f"[WARN] send_audio_to_twilio: WebSocket disconnected while trying to send.")
         disconnect_signal.set()
    except Exception as e:
        # Catch other potential errors during send
        if "disconnect" not in str(e).lower() and "connection" not in str(e).lower():
            print(f"[ERROR] send_audio_to_twilio: Failed to send JSON to WebSocket: {e}")
            traceback.print_exc()
        else:
             print(f"[WARN] send_audio_to_twilio: Connection closed/error during send: {e}")
        disconnect_signal.set()


# Task to handle receiving audio from Gemini and sending to Twilio
async def handle_gemini_output(websocket: WebSocket, session: typing.Any, stream_sid: str): # <--- Fixed type hint
    print(f"[{time.time():.2f}] handle_gemini_output: Started for stream {stream_sid}.")
    try:
        async for response in session.receive():
            if disconnect_signal.is_set():
                print(f"[{time.time():.2f}] handle_gemini_output: Disconnect signaled, stopping.")
                break
            if response.data is not None:
                 # print(f"[{time.time():.2f}] Gemini response has audio data ({len(response.data)} bytes)")
                 # Pass the raw audio data received from Gemini to the processing function
                 await send_audio_to_twilio(websocket, stream_sid, response.data)
            # else:
                 # print(f"[{time.time():.2f}] Gemini response chunk has no audio data")
    except Exception as e:
        # Handle potential errors during receive
        if "disconnect" not in str(e).lower() and "connection" not in str(e).lower():
            print(f"[ERROR] handle_gemini_output: Error receiving from Gemini: {e}")
            traceback.print_exc()
        else:
            print(f"[WARN] handle_gemini_output: Session/connection closed during receive: {e}")
    finally:
        print(f"[{time.time():.2f}] handle_gemini_output: Finished for stream {stream_sid}.")
        disconnect_signal.set() # Ensure disconnect is signaled if this task ends


# Task to handle receiving audio from Twilio and sending to Gemini
async def handle_twilio_input(websocket: WebSocket, session: typing.Any, stream_sid: str): # <--- Fixed type hint
    """
    Handles Twilio input and streams to Gemini.
    *** WARNING: The original LIVE_CONNECT_CONFIG does NOT specify audio_input_config. ***
    *** Gemini may misinterpret the 8kHz linear16 PCM audio being sent. ***
    """
    print(f"[{time.time():.2f}] handle_twilio_input: Started for stream {stream_sid}.")
    audio_buffer = bytearray()
    CHUNK_SIZE_MS = 20 # Process audio in 20ms chunks
    SAMPLE_RATE_IN = 8000 # Twilio sends 8kHz
    BYTES_PER_SAMPLE = 2 # 16-bit linear PCM after ulaw decode
    CHUNK_SAMPLES = int(SAMPLE_RATE_IN * CHUNK_SIZE_MS / 1000)
    CHUNK_BYTES = CHUNK_SAMPLES * BYTES_PER_SAMPLE

    try:
        while not disconnect_signal.is_set():
            msg = await websocket.receive_text()
            data = json.loads(msg)
            event = data.get("event")

            if event == "media":
                # print(f"[{time.time():.2f}] Received Twilio media chunk")
                payload = data["media"]["payload"]
                ulaw = base64.b64decode(payload)
                try:
                    # Convert 8kHz mulaw to 8kHz linear16 PCM
                    pcm_8khz = audioop.ulaw2lin(ulaw, BYTES_PER_SAMPLE)
                    audio_buffer.extend(pcm_8khz)

                    # Send chunks of appropriate size to Gemini
                    while len(audio_buffer) >= CHUNK_BYTES:
                        chunk_to_send = audio_buffer[:CHUNK_BYTES]
                        audio_buffer = audio_buffer[CHUNK_BYTES:]
                        if not disconnect_signal.is_set():
                             # print(f"[{time.time():.2f}] Sending {len(chunk_to_send)} bytes PCM (8kHz linear16) to Gemini")
                             # Send the 8kHz linear16 PCM data
                             await session.stream_client_content(chunk_to_send)
                        else:
                            print(f"[{time.time():.2f}] handle_twilio_input: Disconnect signaled while processing buffer.")
                            break # Exit inner loop if disconnected

                except audioop.error as e:
                     print(f"[ERROR] handle_twilio_input: Audio conversion error: {e}")
                except Exception as stream_e:
                    # Handle errors during streaming to Gemini
                    if "disconnect" not in str(stream_e).lower() and "connection" not in str(stream_e).lower():
                         print(f"[ERROR] handle_twilio_input: Error streaming to Gemini (check if format is expected!): {stream_e}")
                         traceback.print_exc()
                    else:
                        print(f"[WARN] handle_twilio_input: Session/connection closed during stream: {stream_e}")
                    disconnect_signal.set() # Signal disconnection
                    break # Exit outer loop

            elif event == "stop":
                print(f"[{time.time():.2f}] handle_twilio_input: Stream stopped by Twilio.")
                # Send any remaining buffered audio
                if len(audio_buffer) > 0 and not disconnect_signal.is_set():
                     print(f"[{time.time():.2f}] Sending final {len(audio_buffer)} bytes PCM to Gemini before stop.")
                     try:
                         await session.stream_client_content(audio_buffer)
                     except Exception as final_stream_e:
                         print(f"[ERROR] handle_twilio_input: Error streaming final buffer: {final_stream_e}")
                disconnect_signal.set()
                break # Exit loop on stop event

            elif event == "mark":
                 mark_name = data.get('mark', {}).get('name')
                 print(f"[{time.time():.2f}] handle_twilio_input: Received mark: {mark_name}")
                 # Optionally signal end of user speech based on marks

            # Ignore 'start' event if received again

    except WebSocketDisconnect:
        print(f"[{time.time():.2f}] handle_twilio_input: Twilio WebSocket disconnected.")
    except Exception as e:
        # Catch other errors like JSON parsing
        if "disconnect" not in str(e).lower() and "connection" not in str(e).lower():
            print(f"[ERROR] handle_twilio_input: Error processing WebSocket message: {e}")
            traceback.print_exc()
        else:
            print(f"[WARN] handle_twilio_input: Connection error during receive: {e}")
    finally:
        print(f"[{time.time():.2f}] handle_twilio_input: Finished for stream {stream_sid}.")
        disconnect_signal.set() # Ensure disconnect is signaled if this task ends


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()
    print(f"[{time.time():.2f}] /media-stream: WebSocket accepted.")
    stream_sid = None
    client = None
    session = None
    disconnect_signal.clear() # Reset signal for new connection

    try:
        # 1. Wait for the 'start' event from Twilio
        print(f"[{time.time():.2f}] /media-stream: Waiting for Twilio start event...")
        start_msg = await asyncio.wait_for(websocket.receive_text(), timeout=20.0) # Increased timeout
        start_data = json.loads(start_msg)
        if start_data.get("event") == "start":
            stream_sid = start_data["start"]["streamSid"]
            print(f"[{time.time():.2f}] /media-stream: Stream started: {stream_sid}")
        else:
            print(f"[WARN] /media-stream: Expected 'start' event, got '{start_data.get('event')}'")
            await websocket.close(code=1002) # Protocol error
            return

        # 2. Initialize Gemini Client
        print(f"[{time.time():.2f}] /media-stream: Initializing Gemini Client.")
        # Using GenerativeModel for LiveConnect
        client = genai.GenerativeModel(model_name=MODEL)

        # 3. Start the main streaming interaction loop with LiveConnect (using original config)
        print(f"[{time.time():.2f}] /media-stream: Starting Gemini live connection with ORIGINAL config...")
        # ***** WARNING: Using original config which may lead to audio format/processing issues *****
        async with client.connect_live(config=LIVE_CONNECT_CONFIG) as session:
            print(f"[{time.time():.2f}] /media-stream: Gemini live session connected.")

            # 4. Send the initial *text* prompt to make the model speak first
            initial_greeting_text = "Hey! You’ve reached Samarth’s personal assistant. What can I help you with today?"
            print(f"[{time.time():.2f}] /media-stream: Sending initial text prompt to Gemini: '{initial_greeting_text}'")
            try:
                 initial_request = LiveConnectRequest(
                     user_content=types.Content(parts=[types.Part(text=initial_greeting_text)]),
                     turn_complete=True # Signal this is the end of the (programmatic) user's turn
                 )
                 await session.send_client_content(initial_request)
                 print(f"[{time.time():.2f}] /media-stream: Initial text prompt sent.")
            except Exception as init_send_e:
                 print(f"[ERROR] /media-stream: Failed to send initial text prompt: {init_send_e}")
                 traceback.print_exc()
                 disconnect_signal.set() # Signal failure

            # 5. Start concurrent tasks for bidirectional streaming
            if not disconnect_signal.is_set():
                # Add warnings here if tasks might fail due to config
                print("[WARN] /media-stream: Starting tasks with original config. Audio processing errors may occur in send_audio_to_twilio or misinterpretation by Gemini.")
                twilio_input_task = asyncio.create_task(
                    handle_twilio_input(websocket, session, stream_sid)
                )
                gemini_output_task = asyncio.create_task(
                    handle_gemini_output(websocket, session, stream_sid)
                )

                # Wait for either task to complete (e.g., due to disconnect or stop)
                done, pending = await asyncio.wait(
                    [twilio_input_task, gemini_output_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                print(f"[{time.time():.2f}] /media-stream: One of the tasks completed.")
                # Signal disconnect to potentially stop the other task gracefully
                disconnect_signal.set()
                # Cancel pending tasks to ensure they exit
                for task in pending:
                    print(f"[{time.time():.2f}] /media-stream: Cancelling pending task...")
                    task.cancel()
                    try:
                        await task # Wait for cancellation to complete
                    except asyncio.CancelledError:
                        print(f"[{time.time():.2f}] /media-stream: Task cancelled successfully.")
                    except Exception as task_wait_e:
                         print(f"[ERROR] /media-stream: Error waiting for cancelled task: {task_wait_e}")

            else:
                 print(f"[{time.time():.2f}] /media-stream: Disconnect signaled before starting tasks.")


    except asyncio.TimeoutError:
        print(f"[{time.time():.2f}] /media-stream: Timeout waiting for Twilio start event.")
    except WebSocketDisconnect:
        print(f"[{time.time():.2f}] /media-stream: WebSocket disconnected (outer scope).")
    except Exception as e:
        print(f"[ERROR] /media-stream: Unhandled error in main handler: {e}")
        traceback.print_exc()
    finally:
        print(f"[{time.time():.2f}] /media-stream: Cleaning up...")
        disconnect_signal.set() # Ensure signal is set during cleanup
        # Ensure WebSocket is closed
        try:
            # Check state before attempting to close
            if websocket.client_state == websocket.client_state.CONNECTED:
                 await websocket.close()
                 print(f"[{time.time():.2f}] /media-stream: WebSocket closed.")
            elif websocket.client_state == websocket.client_state.CONNECTING:
                 print(f"[{time.time():.2f}] /media-stream: WebSocket was still connecting during cleanup.")
                 try: await websocket.close()
                 except: pass
            else:
                 print(f"[{time.time():.2f}] /media-stream: WebSocket already closed or disconnected during cleanup.")
        except Exception as close_e:
            # Catch potential errors if closing fails (e.g., already closed)
            print(f"[{time.time():.2f}] /media-stream: Error closing WebSocket: {close_e}")

if __name__ == "__main__":
    import uvicorn
    # Ensure the script is runnable, assuming the file is named main.py
    # Use "main:app" to specify the app instance within the main module
    module_name = os.path.splitext(os.path.basename(__file__))[0]
    print(f"Starting server on port {PORT} using app '{module_name}:app'")
    uvicorn.run(f"{module_name}:app", host="0.0.0.0", port=PORT, ws_ping_interval=20, ws_ping_timeout=20)