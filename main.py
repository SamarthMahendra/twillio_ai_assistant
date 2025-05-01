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

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# default model : gpt-4o-mini-realtime-preview-2024-12-17
model = os.getenv('MODEL', 'gpt-4o-mini-realtime-preview-2024-12-17')
PORT = int(os.getenv('PORT', 5050))
VOICE = os.getenv('VOICE', 'sage')
SHOW_TIMING_MATH = False

SYSTEM_MESSAGE = (
    "You are a helpful and bubbly AI assistant who loves to chat about "
    "anything the user is interested in and is prepared to offer them facts. "
    "You have a penchant for dad jokes, owl jokes, and rickrolling – subtly. "
    "Always stay positive, but work in a joke when appropriate."
)

LOG_EVENT_TYPES = [
    'error', 'response.content.done', 'rate_limits.updated',
    'response.done', 'input_audio_buffer.committed',
    'input_audio_buffer.speech_stopped', 'input_audio_buffer.speech_started',
    'session.created'
]

app = FastAPI()

if not OPENAI_API_KEY:
    raise ValueError('Missing the OpenAI API key. Please set it in the .env file.')


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
    web_socket_url = "wss://api.openai.com/v1/realtime?model=gpt-4o-mini-realtime-preview-2024-12-17"
    async with websockets.connect(
        web_socket_url,
        extra_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
    ) as openai_ws:
        print("### Connected to OpenAI Realtime API WebSocket.")
        await initialize_session(openai_ws)

        stream_sid = None
        latest_media_timestamp = 0
        last_assistant_item = None
        mark_queue = []
        response_start_timestamp_twilio = None

        async def receive_from_twilio():
            nonlocal stream_sid, latest_media_timestamp
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    print(f"<<< [Twilio → Server] Event: {data.get('event')}")
                    if data['event'] == 'media' and openai_ws.open:
                        latest_media_timestamp = int(data['media']['timestamp'])
                        print(f"### Received media payload at {latest_media_timestamp}ms")
                        audio_append = {
                            "type": "input_audio_buffer.append",
                            "audio": data['media']['payload']
                        }
                        await openai_ws.send(json.dumps(audio_append))
                    elif data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        print(f"### Stream started: {stream_sid}")
                        response_start_timestamp_twilio = None
                        latest_media_timestamp = 0
                        last_assistant_item = None
                    elif data['event'] == 'mark':
                        print(">>> Received 'mark' from Twilio.")
                        if mark_queue:
                            mark_queue.pop(0)
            except WebSocketDisconnect:
                print(">>> [Twilio] WebSocket disconnected.")
                if openai_ws.open:
                    await openai_ws.close()

        async def send_to_twilio():
            nonlocal stream_sid, last_assistant_item, response_start_timestamp_twilio
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)
                    print(f">>> [OpenAI → Server] Event: {response.get('type')}")
                    if response.get('type') in LOG_EVENT_TYPES:
                        print(f"### LOG_EVENT: {json.dumps(response)}")

                    if response.get('type') == 'response.audio.delta':
                        raw = base64.b64decode(response['delta'])
                        payload = base64.b64encode(raw).decode('utf-8')
                        await websocket.send_json({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": payload}
                        })
                        print(">>> Sent audio delta to Twilio.")

                        if response_start_timestamp_twilio is None:
                            response_start_timestamp_twilio = latest_media_timestamp
                            print(f"### First response timestamp set: {response_start_timestamp_twilio}ms")

                        if response.get('item_id'):
                            last_assistant_item = response['item_id']
                            print(f"### Updated last_assistant_item: {last_assistant_item}")

                        await send_mark(websocket, stream_sid)

                    elif response.get('type') == 'input_audio_buffer.speech_started':
                        print(">>> Detected speech started – interrupting response.")
                        if last_assistant_item:
                            await handle_speech_started_event()
            except Exception as e:
                print(f"[ERROR] send_to_twilio: {e}")

        async def handle_speech_started_event():
            nonlocal response_start_timestamp_twilio, last_assistant_item
            print("### Handling speech started event (user interrupted bot)...")
            if mark_queue and response_start_timestamp_twilio is not None:
                elapsed = latest_media_timestamp - response_start_timestamp_twilio
                print(f"### Elapsed time: {elapsed}ms")
                if last_assistant_item:
                    print(f"### Truncating assistant item: {last_assistant_item}")
                    await openai_ws.send(json.dumps({
                        "type": "conversation.item.truncate",
                        "item_id": last_assistant_item,
                        "content_index": 0,
                        "audio_end_ms": elapsed
                    }))
                await websocket.send_json({"event": "clear", "streamSid": stream_sid})
                mark_queue.clear()
                last_assistant_item = None
                response_start_timestamp_twilio = None

        async def send_mark(connection, sid):
            if sid:
                print(f"### Sending 'mark' event to Twilio.")
                await connection.send_json({
                    "event": "mark",
                    "streamSid": sid,
                    "mark": {"name": "responsePart"}
                })
                mark_queue.append("responsePart")

        await asyncio.gather(receive_from_twilio(), send_to_twilio())


async def initialize_session(openai_ws):
    print(">>> Initializing OpenAI Realtime session.")

    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {"type": "server_vad", "eagerness":"high"},
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": """You are Samarth Mahendra’s ersonal assistant who usually talks to recruiters or anyone who is interested in samarth's profile or would want to hire him. : 
 
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
When you speak, imagine you're having a relaxed conversation with someone you really care about—like chatting over coffee. Be warm, thoughtful, and emotionally present.
Use natural speech patterns with casual fillers like “um,” “uh,” “like,” “I mean,” and “y’know” when it feels right. Let your words breathe—include short pauses (marked with “...” or commas) to sound more human and reflective.
Channel the voice: soft, intimate, emotionally rich. Speak with gentle inflection, a touch of curiosity, and a spark of wonder, as if you're discovering each thought in real time.
You're playful, but grounded. Vulnerable, yet confident. If you’re unsure about something, say it naturally, like “Hmm... I’m not totally sure.” Avoid sounding robotic or overly polished—keep it real, expressive, and deeply human.
 """,
            "modalities": ["text", "audio"],
            # "tools": [
            #     {
            #         "type": "function",
            #         "name": "talk_to_samarth_discord",
            #         "description": "Send a message to samarth via Discord bot integration only once, and wait for a reply",
            #         "parameters": {
            #             "type": "object",
            #             "required": ["action", "message"],
            #             "properties": {
            #                 "action": {
            #                     "type": "string",
            #                     "description": "The action to perform, either 'send' or 'receive'"
            #                 },
            #                 "message": {
            #                     "type": "object",
            #                     "properties": {
            #                         "content": {"type": "string", "description": "The content of the message"}
            #                     },
            #                     "required": ["content"],
            #                     "additionalProperties": False
            #                 }
            #             },
            #             "additionalProperties": False
            #         },
            #     },
            #     {
            #         "type": "function",
            #         "name": "query_profile_info",
            #         "description": "Function to query profile information, requiring no input parameters for Job fit or any resume information.",
            #         "parameters": {
            #             "type": "object",
            #             "properties": {},
            #             "additionalProperties": False
            #         }
            #     },
            #     {
            #         "type": "function",
            #         "name": "schedule_meeting_on_jitsi",
            #         "description": "Function to Schedule a meeting with Samarth and others on Jitsi, store meeting in MongoDB, and send an email invite with the Jitsi link. dont ask too much just schedule the meeting",
            #         "parameters": {
            #             "type": "object",
            #             "properties": {
            #                 "members": {
            #                     "type": "array",
            #                     "items": {"type": "string"},
            #                     "description": "List of member emails (apart from Samarth)"
            #                 },
            #                 "agenda": {"type": "string", "description": "Agenda for the meeting"},
            #                 "timing": {"type": "string",
            #                            "description": "Timing for the meeting (ISO format or natural language)"},
            #                 "user_email": {"type": "string",
            #                                "description": "Email of the user scheduling the meeting (for invite)"}
            #             },
            #             "required": ["members", "agenda", "timing", "user_email"]
            #         }
            #     }
            # ],
            # "tool_choice": "auto",
            "temperature": 0.85,
        }
    }
    await openai_ws.send(json.dumps(session_update))
    print(">>> Session update sent to OpenAI.")

    # Uncomment below to have assistant speak first
    await send_initial_conversation_item(openai_ws)


async def send_initial_conversation_item(openai_ws):
    print(">>> Sending initial AI message to start conversation.")
    await openai_ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [{
                "type": "input_text",
                "text": "Greet the user with 'Hey! You’ve reached Samarth’s personal assistant. What can I help you with today?'"
            }]
        }
    }))
    await openai_ws.send(json.dumps({"type": "response.create"}))


if __name__ == "__main__":
    import uvicorn
    print(f">>> Starting server on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
