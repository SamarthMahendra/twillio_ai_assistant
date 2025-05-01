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
        system_instruction=types.Content(parts=[
                types.Part(
                    text="""
                 You are Samarth personal assistant who usually talks to recruiters or anyone who is interested in samarth's profile or would want to hire him. : 
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
                )
            ]
        ),
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE)
            )
        ),
    )

    # twist: store the Twilio stream SID so we can send back our audio
    stream_sid = None

    async def twilio_audio_stream():
        nonlocal stream_sid
        try:
            while True:
                msg = await websocket.receive_text()
                data = json.loads(msg)
                if data["event"] == "start":
                    stream_sid = data["start"]["streamSid"]
                elif data["event"] == "media":
                    ulaw = base64.b64decode(data["media"]["payload"])
                    pcm = audioop.ulaw2lin(ulaw, 2)
                    yield pcm
                elif data["event"] == "stop":
                    break
        except WebSocketDisconnect:
            pass

    #  ———  HERE’S THE KEY CHANGE ———
    async with client.aio.live.connect(model=MODEL, config=config) as session:
        # **send a text turn** so Gemini will generate audio immediately
        await session.send(
            input="Hello! This is Samarth’s personal assistant—how can I help you today?",
            end_of_turn=True
        )

        # now pipe Twilio’s audio in and Gemini’s audio out
        async for response in session.start_stream(
            stream=twilio_audio_stream(),
            mime_type="audio/pcm"
        ):
            if getattr(response, 'data', None):
                pcm_out = response.data
                # downsample & µ-law encode for Twilio
                pcm_rs, _ = audioop.ratecv(pcm_out, 2, 1, 24000, 8000, None)
                mulaw = audioop.lin2ulaw(pcm_rs, 2)
                payload = base64.b64encode(mulaw).decode()
                await websocket.send_json({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": payload}
                })

    await websocket.close()


if __name__ == "__main__":
    import uvicorn
    print(f"Starting on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
