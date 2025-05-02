# celery_worker.py

import os
import logging
from celery import Celery
import mongo_tool
import discord_tool
import asyncio

# Set up detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(processName)s %(message)s',
)
logger = logging.getLogger(__name__)

logger.info("[Celery Worker] Starting celery_worker.py")

CELERY_BROKER_URL = os.getenv("REDIS_URL")

CELERY_BROKER_URL = os.getenv("REDIS_URL")
logger.info(f"[Celery Worker] Using broker URL: {CELERY_BROKER_URL}")

celery_app = Celery(
    "celery_worker",
    broker=CELERY_BROKER_URL,
    backend=CELERY_BROKER_URL  # optional, if you want to use Redis for result backend too
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)
logger.info(f"[Celery Worker] Celery configuration: {celery_app.conf}")



@celery_app.task(bind=True)
def tool_call_fn(self, tool_name, call_id, args):
    logger.info(f"[Celery Worker] Received task: tool_call_fn with tool_name={tool_name}, call_id={call_id}, args={args}")
    try:
        if tool_name == "talk_to_samarth_discord":
            logger.info("[Celery Worker] Calling discord_tool.ask_and_get_reply")
            result = discord_tool.ask_and_get_reply(args["message"]["content"])
        elif tool_name == "query_profile_info":
            logger.info("[Celery Worker] Calling mongo_tool.query_mongo_db_for_candidate_profile")
            result = mongo_tool.query_mongo_db_for_candidate_profile()
        elif tool_name == "send_meeting_email":
            logger.info("[Celery Worker] Sending meeting email to %s", args.get("email"))
            import smtplib
            from email.message import EmailMessage
            smtp_host = os.getenv("SMTP_HOST")
            smtp_port = int(os.getenv("SMTP_PORT", 587))
            smtp_user = os.getenv("SMTP_USER")
            smtp_pass = os.getenv("SMTP_PASS")
            sender = smtp_user or "no-reply@samarthmahendra.com"
            recipient = args.get("email")
            meeting_url = args.get("meeting_url")
            subject = "Your Meeting Link with Samarth"
            body = f"Hello,\n\nHere is your Jitsi meeting link: {meeting_url}\n\nSee you there!\n\nRegards,\nSamarth Mahendra"
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = sender
            msg["To"] = recipient
            msg.set_content(body)
            try:
                with smtplib.SMTP(smtp_host, smtp_port) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
                logger.info(f"[Celery Worker] Email sent to {recipient}")
                result = {"status": "sent", "recipient": recipient}
            except Exception as e:
                logger.error(f"[Celery Worker] Failed to send email: {e}")
                result = {"status": "error", "error": str(e)}
        else:
            logger.warning(f"[Celery Worker] Unknown tool_name: {tool_name}")
            result = None

        logger.info(f"[Celery Worker] Task result: {result}")
        if call_id:
            mongo_tool.save_tool_message(call_id, tool_name, args, result)
        logger.info(f"[Celery Worker] Saved tool message for call_id={call_id}")
        return result
    except Exception as e:
        logger.error(f"[Celery Worker] Error in tool_call_fn: {e}", exc_info=True)
        raise
