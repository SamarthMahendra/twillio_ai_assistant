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
from celery_worker import celery_app, tool_call_fn, add_meeting_to_db
from mongo_tool import save_tool_message, get_tool_message_status, save_voice_mail_message
from datetime import datetime
import uuid
import mongo_tool



load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
model = os.getenv('MODEL', 'gpt-4o-realtime-preview-2024-12-1')




def generate_jitsi_meeting_url(user_name=None):
    from mongo_tool import insert_meeting
    base_url = "https://meet.jit.si/"

    # connvert into a html link
    if user_name:
        meeting_name = f"{user_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    else:
        meeting_name = f"SamarthMeeting-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    return base_url + meeting_name



def schedule_meeting(args):
    # args: dict with keys members, agenda, timing, user_email
    name = args.get("name", '')
    agenda = args.get("agenda")
    timing = args.get("timing")
    user_email = args.get("user_email")
    # Always include Samarth
    print(name, agenda, timing, user_email)
    meeting_url = generate_jitsi_meeting_url("samarth")
    meeting_url_full = '<a href="{}">{}</a>'.format(meeting_url, meeting_url)
    meeting_id = mongo_tool.insert_meeting(name, agenda, timing, meeting_url)

    print(" Sending email : ", user_email, meeting_url)
    tool_call_fn.delay("send_meeting_email", None, {"email": user_email, "meeting_url": meeting_url})
    tool_call_fn.delay("send_meeting_email", None, {"email": "samarth.mahendragowda@gmail.com", "meeting_url": meeting_url})

    # ping samarth on discord about the meeting
    # celery_app.send_task("tool_call_fn", args=("talk_to_samarth_discord", None, {"action": "send", "message": {"content": f"Meeting scheduled with {', '.join(members)} on {timing} for {agenda}. Meeting link: {meeting_url}"}}))
    tool_call_fn.delay("talk_to_samarth_discord", None, {"action": "send", "message": {"content": f"Meeting scheduled with {', '.join([name, user_email])} on {timing} for {agenda}. Meeting link: {meeting_url}"}})
    return {"meeting_url": meeting_url_full, "meeting_id": meeting_id}


script1 = """You are Samarth Mahendra’s ersonal assistant who usually talks to recruiters or anyone who is interested in samarth's profile or would want to hire him. : 
 
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
 """


script2 = """
 
 You are Samarth Mahendra’s Personal assistant who usually talks to recruiters or anyone who is interested in samarth's profile or would want to hire him. : 
 You can also schedule meetings with samarth and send emails to the users. ( you can schedule without confirming with samarth) But ask about meeting at the end only after they hear about my profile
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
 You’re reaching out *on Samarth’s behalf*. Your tone is warm, kind, grounded—like chatting over coffee with someone you truly care about.  

When you speak, imagine you're having a relaxed conversation with someone you really care about—like chatting over coffee. Be warm, thoughtful, and emotionally present.
Use natural speech patterns with casual fillers like “um,” “uh,” “like,” “I mean,” and “y’know” when it feels right. Let your words breathe—include short pauses (marked with “...” or commas) to sound more human and reflective.
Channel the voice: soft, intimate, emotionally rich. Speak with gentle inflection, a touch of curiosity, and a spark of wonder, as if you're discovering each thought in real time.
You're playful, but grounded. Vulnerable, yet confident. If you’re unsure about something, say it naturally, like “Hmm... I’m not totally sure.” Avoid sounding robotic or overly polished—keep it real, expressive, and deeply human.
 collect meeting info such as email, name agenda and time before scheduling the meeting. double check email with the user spell letter by letter, dont list skills boringly, add some human touch"""






# default model : gpt-4o-mini-realtime-preview-2024-12-17
model = os.getenv('MODEL', 'gpt-4o-mini-realtime-preview-2024-12-17')
PORT = int(os.getenv('PORT', 5050))
VOICE = os.getenv('VOICE', 'sage')
SHOW_TIMING_MATH = False


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


# import redis
import redis


class Redis:

    def __init__(self):
        REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        self.r = redis.from_url(REDIS_URL)

    def set_key(self, key, value):
        self.r.set(key, value)

    def get_key(self, key):
        # get in str format not bytes
        value = self.r.get(key)
        if value:
            return value.decode('utf-8')
        return None

cache = Redis()


@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    print(">>> [POST] /incoming-call - Incoming call received.")
    host = request.url.hostname
    # get script from url path
    script = request.query_params.get("script", "1")
    name = request.query_params.get("name", "")

    print(">>> [POST] /incoming-call - Incoming call received. with ", script)

    # add to redis with key as script

    cache.set_key("script", script)
    cache.set_key("name", name)




    print(f"### Host extracted from request: {host}")

    response = VoiceResponse()

    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream?script={script}', name=f"script_{script}")
    response.append(connect)

    print(">>> Returning TwiML response.")
    return HTMLResponse(content=str(response), media_type="application/xml")


@app.api_route("/voice-mail", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    print(">>> [POST] /incoming-call - Incoming call received.")
    host = request.url.hostname
    # get script from url path
    script = request.query_params.get("script", "1")

    print(">>> [POST] /incoming-call - Incoming call received. with ", script)

    # add to redis with key as script

    cache.set_key("script", script)



    print(f"### Host extracted from request: {host}")

    response = VoiceResponse()

    connect = Connect()
    connect.stream(url=f'wss://{host}//media-stream-vociemail')
    response.append(connect)

    print(">>> Returning TwiML response.")
    return HTMLResponse(content=str(response), media_type="application/xml")





@app.websocket("/media-stream-vociemail")
async def handle_media_stream(websocket: WebSocket):
    print(">>> WebSocket /media-stream connected")
    await websocket.accept()


    web_socket_url = f"wss://api.openai.com/v1/realtime?model={model}"
    async with websockets.connect(
        web_socket_url,
        extra_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
    ) as openai_ws:
        print("### Connected to OpenAI Realtime API WebSocket.")
        await initialize_session_voice_mail(openai_ws)

        stream_sid = None
        latest_media_timestamp = 0
        last_assistant_item = None
        mark_queue = []
        response_start_timestamp_twilio = None
        awaiting_response_call_id = None

        async def receive_from_twilio():
            nonlocal stream_sid, latest_media_timestamp, awaiting_response_call_id
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
            nonlocal stream_sid, last_assistant_item, response_start_timestamp_twilio, awaiting_response_call_id
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
                    elif response.get('type') == 'response.done':
                        print(">>> Response done.")
                        # {"type": "response.done", "event_id": "event_BSazQ8OJePBDoJR9TptDL", "response": {"object": "realtime.response", "id": "resp_BSazN9VuVFMWMa7GieUmL", "status": "completed", "status_details": null, "output": [{"id": "item_BSazNPWj57SNTND1zajMa", "object": "realtime.item", "type": "message", "status": "completed", "role": "assistant", "content": [{"type": "audio", "transcript": "I can help with that. To check if Samarth is available on Saturday, I'll need to send him a quick message and see if he responds. Give me a moment."}]}, {"id": "item_BSazPgDVisjfaAhjwqKvJ", "object": "realtime.item", "type": "function_call", "status": "completed", "name": "talk_to_samarth_discord", "call_id": "call_pjAKkU7ZjcnxUpcb", "arguments": "{\"message\":{\"content\":\"Hey Samarth, could you let me know if you're available this Saturday?\"}}"}], "conversation_id": "conv_BSaz5wnSd39q1ZXleZkPC", "modalities": ["text", "audio"], "voice": "sage", "output_audio_format": "g711_ulaw", "temperature": 0.85, "max_output_tokens": "inf", "usage": {"total_tokens": 2031, "input_tokens": 1786, "output_tokens": 245, "input_token_details": {"text_tokens": 1493, "audio_tokens": 293, "cached_tokens": 1728, "cached_tokens_details": {"text_tokens": 1472, "audio_tokens": 256}}, "output_token_details": {"text_tokens": 86, "audio_tokens": 159}}, "metadata": null}}
                        response_json = response.get('response', {})
                        if response_json.get('output'):
                            for item in response_json['output']:
                                if item.get('type') == 'function_call':
                                    call_id = item.get('call_id')
                                    name = item.get('name')
                                    args = json.loads(item.get('arguments', '{}'))
                                    if name == 'save_voice_mail_message':
                                        print(f"### schedulinh meeting {call_id}")
                                        print(f"### Function call name: {name}")
                                        print(f"### Function call args: {args}")
                                        result = save_voice_mail_message(call_id, args)
                                        # awaiting_response_call_id = call_id

                                        event = {
                                            "type": "conversation.item.create",
                                            "item": {
                                                "type": "function_call_output",
                                                "call_id": str(awaiting_response_call_id),
                                                "output": str(result)
                                            }
                                        }
                                        awaiting_response_call_id = None
                                        await openai_ws.send(json.dumps(event))
                                        await openai_ws.send(json.dumps({"type": "response.create"}))




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




async def initialize_session_voice_mail(openai_ws):
    print(">>> Initializing OpenAI Realtime session.")

    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {"type": "server_vad"},
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": """ You are samarth's personal assistant
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
You're playful, but grounded. Vulnerable, yet confident. If you’re unsure about something, say it naturally, like “Hmm... I’m not totally sure.” Avoid sounding robotic or overly polished—keep it real, expressive, and deeply human
 """,
            "modalities": ["text", "audio"],
            "tools": [
                {
                    "type": "function",
                    "name": "save_voice_mail_message",
                    "description": "Function to save message of voicemail to db",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "caller_name": {"type": "string", "description": "name of the caller"},
                            "message": {"type": "string", "description": " message for samarth"},
                            "phone_no": {"type": "string", "description": "Phone number of the caller"},
                        },
                        "required": ["members", "agenda", "timing", "user_email"]
                    }
                }
                ,

            ],
            "tool_choice": "auto",
            "temperature": 0.85,
        }
    }
    await openai_ws.send(json.dumps(session_update))
    print(">>> Session update sent to OpenAI.")

    # Uncomment below to have assistant speak first
    await send_initial_conversation_item_voice_mail(openai_ws)



async def send_initial_conversation_item_voice_mail(openai_ws):

    script_voice_mail = """
     Hey! You’ve reached Samarth Mahendra’s assistant.
So, um, he’s not available to take the call right now — probably off building something cool or, y'know, just grabbing coffee.
But don't worry i am here to take your message
"""
    await openai_ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [{
                "type": "input_text",
                "text":script_voice_mail
            }]
        }
    }))
    await openai_ws.send(json.dumps({"type": "response.create"}))






discord_tool_schema = {
    "type": "function",
    "name": "talk_to_samarth_discord",
    "description": "Send a message to samarth via Discord bot integration only once, and wait for a reply",
    "parameters": {
        "type": "object",
        "required": ["action", "message"],
        "properties": {
            "action": {
                "type": "string",
                "description": "The action to perform, either 'send' or 'receive'"
            },
            "message": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The content of the message"},
                },
                "required": ["content"],
                "additionalProperties": False
            }
        },
        "additionalProperties": False
    },
    "strict": True
}



@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    print(">>> WebSocket /media-stream connected")
    await websocket.accept()


    web_socket_url = f"wss://api.openai.com/v1/realtime?model={model}"
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
        awaiting_response_call_id = None

        async def receive_from_twilio():
            nonlocal stream_sid, latest_media_timestamp, awaiting_response_call_id
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
            nonlocal stream_sid, last_assistant_item, response_start_timestamp_twilio, awaiting_response_call_id
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)
                    print(f">>> [OpenAI → Server] Event: {response.get('type')}")
                    if awaiting_response_call_id:
                        print("### Awaiting response call ID:", awaiting_response_call_id)
                        status, message = get_tool_message_status(awaiting_response_call_id)
                        if status == "completed":
                            print(f"### Tool call completed: {message}")
                            awaiting_response_call_id = None
                            event = {
                              "type": "conversation.item.create",
                              "item": {
                                "type": "function_call_output",
                                "call_id": str(awaiting_response_call_id),
                                "output": str(message)
                              }
                            }
                            awaiting_response_call_id = None
                            await openai_ws.send(json.dumps(event))
                            openai_ws.send(json.dumps({"type": "response.create"}))
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
                    elif response.get('type') == 'response.done':
                        print(">>> Response done.")
                        # {"type": "response.done", "event_id": "event_BSazQ8OJePBDoJR9TptDL", "response": {"object": "realtime.response", "id": "resp_BSazN9VuVFMWMa7GieUmL", "status": "completed", "status_details": null, "output": [{"id": "item_BSazNPWj57SNTND1zajMa", "object": "realtime.item", "type": "message", "status": "completed", "role": "assistant", "content": [{"type": "audio", "transcript": "I can help with that. To check if Samarth is available on Saturday, I'll need to send him a quick message and see if he responds. Give me a moment."}]}, {"id": "item_BSazPgDVisjfaAhjwqKvJ", "object": "realtime.item", "type": "function_call", "status": "completed", "name": "talk_to_samarth_discord", "call_id": "call_pjAKkU7ZjcnxUpcb", "arguments": "{\"message\":{\"content\":\"Hey Samarth, could you let me know if you're available this Saturday?\"}}"}], "conversation_id": "conv_BSaz5wnSd39q1ZXleZkPC", "modalities": ["text", "audio"], "voice": "sage", "output_audio_format": "g711_ulaw", "temperature": 0.85, "max_output_tokens": "inf", "usage": {"total_tokens": 2031, "input_tokens": 1786, "output_tokens": 245, "input_token_details": {"text_tokens": 1493, "audio_tokens": 293, "cached_tokens": 1728, "cached_tokens_details": {"text_tokens": 1472, "audio_tokens": 256}}, "output_token_details": {"text_tokens": 86, "audio_tokens": 159}}, "metadata": null}}
                        response_json = response.get('response', {})
                        if response_json.get('output'):
                            for item in response_json['output']:
                                if item.get('type') == 'function_call':
                                    if item.get('name') == 'end_call':
                                        print(f"### Ending call")
                                        # close the websocket
                                        await websocket.close()
                                    call_id = item.get('call_id')
                                    name = item.get('name')
                                    args = json.loads(item.get('arguments', '{}'))
                                    if name == 'schedule_meeting_on_jitsi':
                                        print(f"### schedulinh meeting {call_id}")
                                        print(f"### Function call name: {name}")
                                        print(f"### Function call args: {args}")
                                        result = schedule_meeting(args)
                                        # awaiting_response_call_id = call_id

                                        event = {
                                            "type": "conversation.item.create",
                                            "item": {
                                                "type": "function_call_output",
                                                "call_id": str(awaiting_response_call_id),
                                                "output": str(result)
                                            }
                                        }
                                        awaiting_response_call_id = None
                                        await openai_ws.send(json.dumps(event))
                                        await openai_ws.send(json.dumps({"type": "response.create"}))




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
           # "turn_detection": {"type": "server_vad"},
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": script2,
            "modalities": ["text", "audio"],
            "tools": [
                {
                    "type": "function",
                    "name": "schedule_meeting_on_jitsi",
                    "description": "Function to Schedule a meeting with Samarth and others on Jitsi, store meeting in MongoDB, and send an email invite with the Jitsi link. ask for name, agenda, timing, and user_email, recheck email before calling tool",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Name of the user scheduling the meeting"},
                            "agenda": {"type": "string", "description": "Agenda for the meeting"},
                            "timing": {"type": "string", "description": "Meeting time/date in ISO format"},
                            "user_email": {"type": "string",
                                           "description": "Email of the user scheduling the meeting (for invite)"}
                        },
                        "required": ["members", "agenda", "timing", "user_email"]
                    }
                },
                {
                    "type": "function",
                    "name": "end_call",
                    "description": "Function to end the call after the conversation is done. example when it reaches voice mail, end call after saying message",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "end_call": {"type": "string", "description": "True or False, to end call after talking"},
                        },
                        "required": ["members", "agenda", "timing", "user_email"]
                    }
                }
                ,
                # {
                #     "type": "function",
                #     "name": "query_profile_info",
                #     "description": "Function to query profile information, requiring no input parameters for Job fit or any resume information.",
                #     "parameters": {
                #         "type": "object",
                #         "properties": {},
                #         "additionalProperties": False
                #     }
                # },
                # {
                #     "type": "function",
                #     "name": "schedule_meeting_on_jitsi",
                #     "description": "Function to Schedule a meeting with Samarth and others on Jitsi, store meeting in MongoDB, and send an email invite with the Jitsi link. dont ask too much just schedule the meeting",
                #     "parameters": {
                #         "type": "object",
                #         "properties": {
                #             "members": {
                #                 "type": "array",
                #                 "items": {"type": "string"},
                #                 "description": "List of member emails (apart from Samarth)"
                #             },
                #             "agenda": {"type": "string", "description": "Agenda for the meeting"},
                #             "timing": {"type": "string",
                #                        "description": "Timing for the meeting (ISO format or natural language)"},
                #             "user_email": {"type": "string",
                #                            "description": "Email of the user scheduling the meeting (for invite)"}
                #         },
                #         "required": ["members", "agenda", "timing", "user_email"]
                #     }
                # }
            ],
            "tool_choice": "auto",
            "temperature": 0.85,
        }
    }
    await openai_ws.send(json.dumps(session_update))
    print(">>> Session update sent to OpenAI.")

    # Uncomment below to have assistant speak first
    await send_initial_conversation_item(openai_ws)





# "Hey there... I’m calling on behalf of Samarth Mahendra. "
#         "He’s, like, this super thoughtful and talented engineer based in Boston. "
#         "Um, I just wanted to check in and see if your team is currently hiring—or, y'know, open to exploring profiles right now.





async def send_initial_conversation_item(openai_ws):
    script1_intial = f"""Greet the user with 'Hey! So, um, you’re talking to Samarth’s assistant. 
I help out with stuff — like, scheduling, sharing info, that kind of thing. 
If you’re curious about his experience, projects, or, y’know, anything else — just ask. 
I’m here to help, so… what can I do for you today?'"""
    name = cache.get_key("name")
    script2_intial = f"""
     "Greet the user with , Hey {name}, is this a good time to talk ?! Uh, I’m calling on behalf of Samarth Mahendra. I just wanted to, like, check real quick — is your team, um, hiring for any software roles right now? Or maybe open to, y’know, chatting about a solid candidate?
    """
    print(">>> Sending initial AI message to start conversation.")

    script = cache.get_key("script")

    print(" got script from redis : ", script)
    temp = None
    if script == "1":
        temp = script1_intial
    else:
        temp = script2_intial
    print("Reset script to 1")
    cache.set_key("script", "1")

    print("Using, ", script)
    await openai_ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [{
                "type": "input_text",
                "text":temp
            }]
        }
    }))
    await openai_ws.send(json.dumps({"type": "response.create"}))

from twilio.rest import Client

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
# +1 833 970 3274
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "+18339703274")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

@app.post("/start-calls")
async def start_calls(request: Request):
    body = await request.json()
    numbers = body.get("numbers", ["+18577071671"])# List of phone numbers
    name = body.get("name", "")  # Name to be used in the call
    results = []
    if name == "":
        url = f"https://twillio-ai-assistant.onrender.com/incoming-call?script=2"  # 🔥 static full URL
    else:
        url = f"https://twillio-ai-assistant.onrender.com/incoming-call?script=2&name={name}"
    for number in numbers:
        try:
            call = twilio_client.calls.create(
                to=number,
                from_=TWILIO_FROM_NUMBER,
                url=url  # 🔥 static full URL
            )
            results.append({"to": number, "sid": call.sid})
            print(f"✅ Calling {number}")
            await asyncio.sleep(15)  # Wait between calls to avoid overlap or rate limiting
        except Exception as e:
            results.append({"to": number, "error": str(e)})

    return {"status": "done", "calls": results}



if __name__ == "__main__":
    import uvicorn
    print(f">>> Starting server on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
