import os
from pymongo import MongoClient
from dotenv import load_dotenv
import datetime


load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://stackoverflow:stackoverflow%40123@cluster0.3kqbc.mongodb.net/myDatabase?retryWrites=true&w=majority&appName=Cluster0")
DB_NAME = os.getenv("MONGO_DB_NAME", "profile_db")
COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "candidate_profiles")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]




def insert_meeting(members, agenda, timing, meeting_url):
    """Insert a meeting into the MongoDB 'meetings' collection."""
    meeting_doc = {
        "members": members,  # list of emails or names
        "agenda": agenda,
        "timing": timing,  # should be a datetime object or ISO string
        "meeting_url": meeting_url,
        "created_at": datetime.datetime.utcnow()
    }
    meetings_collection = db["meetings"]
    result = meetings_collection.insert_one(meeting_doc)
    return str(result.inserted_id)


def insert_into_results(user, id, result):
    """Insert a result into the MongoDB collection."""
    result_dict = {
        "user": user,
        "id": id,
        "result": result,
        "timestamp": datetime.datetime.utcnow()
    }
    results_collection = db["results"]
    result = results_collection.insert_one(result_dict)
    return str(result.inserted_id)

def query_mongo_db_for_results(user, id):
    """Query the results collection for a specific user and ID, sorted by timestamp and return the first match."""
    results_collection = db["results"]
    result = results_collection.find_one({"user": user, "id": id}, {"_id": 0, "result": 1})
    if not result:
        return {"error": "Results not found"}
    return result["result"]


def insert_candidate_profile(profile_dict):
    """Insert a candidate profile into the MongoDB collection."""
    result = collection.insert_one(profile_dict)
    return str(result.inserted_id)

def query_mongo_db_for_candidate_profile():
    """Query the candidate profile collection for Samarth Mahendra and return the first match as a JSON-serializable dict."""
    profile = collection.find_one({"name": "Samarth Mahendra"})
    if not profile:
        return {"error": "Profile not found"}
    profile.pop('_id', None)
    def serialize_value(val):
        if isinstance(val, list):
            # If it's a list of dicts, keep as is; if list of primitives, join as string
            if all(isinstance(item, dict) for item in val):
                return val
            return ', '.join(str(item) for item in val)
        if isinstance(val, dict):
            return {k: serialize_value(v) for k, v in val.items()}
        return val

    profile = {k: serialize_value(v) for k, v in profile.items()}
    return profile

    # Ensure all values are JSON-serializable and readable
def save_tool_message(call_id, name, args, result):
    """Save a tool message to the messages collection."""
    message_dict = {
        "message_id": call_id,
        "tool_name": name,
        "args": args,
        "content": result,
        "timestamp": datetime.datetime.utcnow(),
        "status": "completed" if result else "pending"
    }
    messages_collection = db["messages"]
    insert_result = messages_collection.insert_one(message_dict)
    return str(insert_result.inserted_id)


def save_meeting_via_call(args):
    """Save meeting details via call ID."""
    """properties": {
                            "members": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of member emails (apart from Samarth)"
                            },
                            "agenda": {"type": "string", "description": "Agenda for the meeting"},
                            "timing": {"type": "string", "description": "Meeting time/date in ISO format"},
                            "user_email": {"type": "string",
                                           "description": "Email of the user scheduling the meeting (for invite)"}
                        },
                        "required": ["members", "agenda", "timing", "user_email"]
     """
    meeting_dict = {
        "members": args["members"],
        "agenda": args["agenda"],
        "timing": args["timing"],  # should be a datetime object or ISO string
        "user_email": args["user_email"],

    }
    print(" Inserted meeting details:", meeting_dict)
    meetings_collection = db["meetings_via_calls"]
    insert_result = meetings_collection.insert_one(meeting_dict)
    print(" Inserted meeting ID:", insert_result.inserted_id)
    return str(insert_result.inserted_id)


def get_tool_message_status(message_id):
    """Get the status of a tool message by its ID."""
    print(" [MongoDB] Getting message status for ID:", message_id)


    messages_collection = db["messages"]
    message = messages_collection.find_one({"message_id": message_id})

    if not message:
        return "not_found", {}
    print(message)
    print(" [MongoDB] Message status:", message["status"])
    # Remove MongoDB's _id field which is not JSON serializable
    message.pop('_id', None)
    
    # Return the complete message data
    print(" [MongoDB] Message data:", message["content"])
    return message["status"], message["content"]



if __name__ == "__main__":
    # Insert the complete profile for Samarth Mahendra
    profile_dict = {
        "name": "Samarth Mahendra",
        "headline": "Backend Engineer, LLM & Data Systems Enthusiast",
        "linkedin": "https://www.linkedin.com/in/samarth-mahendra-7aab5a114/",
        "youtube": "https://www.youtube.com/@msamarthmahendra8082",
        "bio": "Currently building a distributed job tracking system (JobStats) and a personal profile website with an agent for interview scheduling. Looking to collaborate on LLM-powered productivity tools, backend infra, or real-time systems. Learning advanced DBs, mobile dev, and distributed design. Ask me about chatbot optimization, API cost reduction, and fun fact: skated 22.3 km in one go!",
        "skills": [
            "Python", "MongoDB", "LLM", "Celery", "Redis", "Prometheus", "Puppeteer", "React", "PostgreSQL", "Django", "TypeScript", "JavaScript", "Linux", "Kubernetes", "Terraform", "AWS", "Azure", "Firebase", "MySQL", "PostgreSQL", "PyTorch", "NumPy", "CuPy", "Multiprocessing", "Jenkins", "Jira", "Git", "GitLab", "Bitbucket", "Android", "C", "C++", "CSS3", "DigitalOcean", "Jest", "SQL", "React", "Pytest"
        ],
        "education": [
            {
                "institution": "Northeastern University, Boston, MA",
                "degree": "Master of Science (MS), Computer Science",
                "dates": "Jan 2024 – Dec 2025",
                "courses": [
                    "CS 5010: Programming Design Paradigm",
                    "CS 5200: Database Management Systems",
                    "CS 5800: Algorithms",
                    "CS 6120: Natural Language Processing",
                    "CS 6140: Machine Learning",
                    "CS 5520: Mobile Application Development",
                    "CS 5500: Foundations of Software Engineering"
                ]
            },
            {
                "institution": "Dayananda Sagar College of Engineering, Bangalore, India",
                "degree": "Bachelor of Engineering (BE), Computer Science",
                "dates": "Aug 2018 – Jul 2022",
                "cgpa": 8.59
            }
        ],
        "experience": [
            {
                "role": "Associate Software Development Engineer – Backend",
                "company": "Draup",
                "type": "Full-time",
                "dates": "Aug 2022 – Nov 2023",
                "location": "Bangalore (Hybrid)",
                "highlights": [
                    "Led platform modules for digital tech stack, outsourcing, and customer intelligence.",
                    "Revamped insights page, boosting engagement by 40%.",
                    "Designed dynamic query generation engine for chatbot pipelines (60% perf. gain, 80% dev time cut).",
                    "Migrated APIs to Elasticsearch for real-time aggregation (5× speedup).",
                    "Introduced advanced Boolean filter logic.",
                    "Built subscription-based access control and enhanced platform performance (400% speedup, 50% cost reduction).",
                    "Reduced downtime from 4% to 1%; resolved issues with Datadog & AWS (75% faster)."
                ]
            },
            {
                "role": "Backend Engineering Intern",
                "company": "Draup",
                "type": "Internship",
                "dates": "Apr 2022 – Jul 2022",
                "location": "Bengaluru",
                "highlights": [
                    "Debugged API issues using Datadog.",
                    "Implemented caching for image requests.",
                    "Created automated DB scripts."
                ]
            },
            {
                "role": "Research Assistant (Patent Co-Inventor)",
                "company": "Dayananda Sagar College of Engineering",
                "type": "Part-time",
                "dates": "Nov 2021 – Sep 2023",
                "location": "Bengaluru (Hybrid)",
                "project": "Myocardium Wall Motion & Thickness Mapping (Patent Pending)",
                "app_no": "202341086278 (India)",
                "highlights": [
                    "Developed novel image processing for MRI cine scans.",
                    "Built algorithms for myocardium thickness + fibrosis mapping.",
                    "Optimized with NumPy, CuPy, multiprocessing."
                ]
            }
        ],
        "projects": [
            {
                "name": "JobStats - FANG Job Trends",
                "description": "Scrapes job data from 15+ platforms with stealth headers & dynamic HTML processing using LLMs; built with Celery, PostgreSQL, Redis, Prometheus, Puppeteer, and React.",
                "github": "https://github.com/SamarthMahendra/StealthProject"
            },
            {"name": "Live Bluetooth Silent Disco", "description": "Real-time audio streaming over WebSockets using Python and BlackHole."},
            {"name": "LinkedInAssist (LLM-powered)", "description": "Chrome extension for filtering LinkedIn jobs using GPT-3.5 + Flask."},
            {"name": "Chatbot for Account Intelligence (Hackathon @ Draup)", "description": "Langchain + RAG, cross-encoder reranking, Redis cache, PostgreSQL backend."},
            {"name": "Unemployment vs Job Openings (Beveridge Curve)", "description": "Labor market analysis using PyTorch and Pandas."},
            {"name": "MapReduce-style Grade Analyzer", "description": "Parallel analysis of student datasets using Python multiprocessing."},
            {"name": "Breast Cancer Detection", "description": "Logistic regression, GNB, GDA for diagnosis classification (scikit-learn)."},
            {"name": "Aspect-Based Sentiment Analysis", "description": "Attention-based LSTM for aspect classification in SemEval datasets (PyTorch)."},
            {"name": "Custom Word2Vec", "description": "Co-occurrence matrix from Merchant of Venice, visualized with PCA."},
            {"name": "Java Portfolio Manager", "description": "MVC-based investment simulator, stock API integration, 100+ JUnit test cases."},
            {"name": "Bike Rental Platform", "description": "BlueBikes clone with React.js, Django REST, Redis, JWT, Azure."},
            {"name": "Myocardium Wall Motion Mapper (Patent Pending)", "description": "Image processing on cine MRI scans for heart wall motion and fibrosis."}
        ],
        "certifications": [
            {"name": "Expert - Programming and Algorithms (CodeSignal)", "credential_id": "cm6lagnfc01ihm8i3wldt2po3"},
            {"name": "Advanced Retrieval for AI with Chroma (DeepLearning.AI)", "credential_id": "e7856493-e9ca-40f3-81a2-62e86fc6267c"},
            {"name": "Supervised ML: Regression & Classification (Stanford / DeepLearning.AI)", "credential_id": "W7RGEA3RE44U"},
            {"name": "Advanced Learning Algorithms (Stanford / DeepLearning.AI)", "credential_id": "PC74JUPWD28G"},
            {"name": "DOM API + JS Programming (CodeSignal)", "credential_id": "cm6po6406007ztmrk4bw7za5o"},
            {"name": "Server-Side Web Scraping (Python + BeautifulSoup, CodeSignal)", "credential_id": "cm6n495fv00twy6hg7w0xihzf"},
            {"name": "Mastering Data Structures & Algorithms in Python (CodeSignal)", "credential_id": "cm0adl6mm004lgpxn4gphel9o"}
        ],
        "fun_fact": "I skated 22.3 km in a single session!"
    }
    print("Inserted profile ID:", insert_candidate_profile(profile_dict))
    # Example: query
    print(query_mongo_db_for_candidate_profile())
