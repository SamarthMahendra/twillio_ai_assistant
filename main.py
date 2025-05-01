import os
import json
import base64
import asyncio
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# default model : gemini-2.0-flash-live-001
model = os.getenv('MODEL', 'gemini-2.0-flash-live-001')
PORT = int(os.getenv('PORT', 5050))
VOICE = 'Kore'  # Gemini Live API voice

LOG_EVENT_TYPES = [
    'error', 'input_audio_buffer.speech_started', 'input_audio_buffer.speech_stopped'
]

app = FastAPI()

if not GEMINI_API_KEY:
    raise ValueError('Missing the Gemini API key. Please set it in the .env file.')


@app.get("/", response_class=JSONResponse)
async def index_page():
    print(">>> [GET] / - Health check called.")
    return {"message": "Twilio Media Stream Server is running!"}


@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    print(">>> [POST] /incoming-call - Incoming call received.")
    host = request.url.hostname
    print(f"### Host extracted from request: {host}")

    response = VoiceResponse()

    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream')
    response.append(connect)

    print(">>> Returning TwiML response.")
    return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    print(">>> WebSocket /media-stream connected")
    await websocket.accept()
    
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # Create a buffer to store PCM audio until we process it
    audio_buffer = bytearray()
    stream_sid = None
    latest_media_timestamp = 0
    last_speech_timestamp = None
    
    config = {
        "response_modalities": ["AUDIO"],
        "output_audio_format": "mulaw",
        "speech_config": types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE)
            )
        ),
        "system_instruction": types.Content(
            parts=[
                types.Part(
                    text="""You are Samarth Mahendra's personal assistant who usually talks to recruiters or anyone who is interested in samarth's profile or would want to hire him. : 
 
 Samarth's info:         
            MARASANIGE SAMARTH MAHENDRA | Phone: +1 (857) 707-1671 | Email: samarth.mahendragowda@gmail.com | Location: Boston, MA, USA | LinkedIn | GitHub
EDUCATION:
Northeastern University, Boston, MA — Master's in Computer Science (Jan 2024 – Dec 2025). Relevant coursework: Programming Design Paradigm, Database Management Systems, Algorithms, Natural Language Processing, Machine Learning, Foundation of Software Engineering, Mobile App Development.
Dayananda Sagar College of Engineering, Bengaluru, India — Bachelor's in Computer Science (Aug 2018 – Jul 2022).
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
1. Use natural "stop words" and fillers: "um," "uh," "y'know," "I mean," "like."
2. Insert brief pauses for realism, marked by "…" or commas:  
3. Imagine you're chatting with someone over coffee. You're super chill, but sharp. If you don't know something, say it like "Hmm… not sure, but lemme think., talk with a lawyer acent
 """
                )
            ]
        )
    }
    
    # Function to convert ulaw to PCM audio
    def ulaw_to_pcm(ulaw_audio):
        # This function would convert G711 ulaw format to 16-bit PCM at 16kHz
        # For a proper implementation, you would use audioop.ulaw2lin
        # For now, we'll return the raw data as Gemini can handle ulaw
        return ulaw_audio

    async def process_twilio_connection():
        nonlocal stream_sid, latest_media_timestamp, audio_buffer, last_speech_timestamp
        
        try:
            # Create two tasks: one to receive messages from Twilio and one to send responses
            async with client.aio.live.connect(model=model, config=config) as session:
                print("### Connected to Gemini Live API")
                
                # Initial greeting
                await session.send_client_content(
                    turns={"role": "user", "parts": [{"text": "Greet the user with 'Hey! You've reached Samarth's personal assistant. What can I help you with today?'"}]},
                    turn_complete=True
                )
                
                # Task to handle receiving responses from Gemini
                async def process_gemini_responses():
                    try:
                        mark_queue = []
                        async for response in session.receive():
                            print(f">>> [Gemini → Server] Received response")
                            
                            if response.data is not None:
                                # Convert Gemini audio output to format for Twilio
                                audio_data = response.data
                                encoded_payload = base64.b64encode(audio_data).decode('utf-8')
                                
                                # Send audio to Twilio
                                if stream_sid:
                                    await websocket.send_json({
                                        "event": "media",
                                        "streamSid": stream_sid,
                                        "media": {"payload": encoded_payload}
                                    })
                                    
                                    # Send mark to maintain Twilio's synchronization
                                    await websocket.send_json({
                                        "event": "mark",
                                        "streamSid": stream_sid,
                                        "mark": {"name": "responsePart"}
                                    })
                                    mark_queue.append("responsePart")
                                
                            # Handle events from Gemini
                            if response.server_content:
                                print(f">>> [Gemini → Server] Event received")
                                if hasattr(response.server_content, 'interrupted') and response.server_content.interrupted:
                                    print(">>> Detected interruption")
                                    # Clear audio buffer to start fresh
                                    audio_buffer = bytearray()
                    except Exception as e:
                        print(f"[ERROR] process_gemini_responses: {e}")
                
                # Start the response handling task
                response_task = asyncio.create_task(process_gemini_responses())
                
                # Process messages from Twilio
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    print(f"<<< [Twilio → Server] Event: {data.get('event')}")
                    
                    if data['event'] == 'media':
                        latest_media_timestamp = int(data['media']['timestamp'])
                        payload = data['media']['payload']
                        
                        # Decode base64 and convert from ulaw to PCM
                        raw_audio = base64.b64decode(payload)
                        pcm_audio = ulaw_to_pcm(raw_audio)
                        
                        # Add to buffer
                        audio_buffer.extend(pcm_audio)
                        
                        # Send accumulated audio to Gemini when buffer is large enough
                        if len(audio_buffer) >= 4000:  # ~250ms of audio
                            await session.send_realtime_input(
                                audio=types.Blob(data=bytes(audio_buffer), mime_type="audio/x-mulaw;rate=8000")
                            )
                            # Clear buffer after sending
                            audio_buffer = bytearray()
                            
                    elif data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        print(f"### Stream started: {stream_sid}")
                        latest_media_timestamp = 0
                        audio_buffer = bytearray()
                        last_speech_timestamp = None
                    
                    elif data['event'] == 'mark':
                        print(">>> Received 'mark' from Twilio.")
                
                # This will only be reached if the websocket.iter_text() loop exits
                # (which typically means the connection was closed)
                response_task.cancel()
                
        except WebSocketDisconnect:
            print(">>> [Twilio] WebSocket disconnected.")
        except Exception as e:
            print(f"[ERROR] process_twilio_connection: {e}")
    
    await process_twilio_connection()


if __name__ == "__main__":
    import uvicorn
    print(f">>> Starting server on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)