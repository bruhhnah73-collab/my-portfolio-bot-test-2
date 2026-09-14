from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from groq import Groq
from email.mime.text import MIMEText

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest

import os
import base64
import re
import secrets
import json
import time
import threading
import hashlib
import psycopg2
from psycopg2.extras import RealDictCursor


# =========================================================
# APP
# =========================================================

app = FastAPI()


# =========================================================
# URLS
# =========================================================

FRONTEND_URL = "https://email-agent-panel.onrender.com"
BACKEND_URL = "https://my-portfolio-bot-test-2.onrender.com"
GOOGLE_CALLBACK_URL = f"{BACKEND_URL}/gmail/callback"


# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# =========================================================
# ENVIRONMENT
# =========================================================

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


# =========================================================
# GMAIL SETTINGS
# =========================================================

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify"
]


# =========================================================
# AGENT
# =========================================================

agent_enabled = True


# =========================================================
# CLASSIFIER SAFETY
# =========================================================

classifier_lock = threading.Lock()
classifier_backoff_until = 0


# =========================================================
# AI CHAT INSTRUCTIONS
# =========================================================

SYSTEM_INSTRUCTION = """
You are an AI assistant representing the creator of this portfolio.

The creator builds and experiments with AI, web development, and technology.

Projects:

1. School Admin Dashboard - 2026
Built using Replit.
A functional administrative login portal and dashboard data interface.

2. School Landing Page - 2026
Built using Visual Studio Code.
A clean, fully responsive multi-page website built for a real school.

3. My First AI Chatbox - 2026
Built using Ziper AI.
An AI chatbox that provides information about the portfolio and projects.

4. Custom Python AI Chatbot
Built using Python, Streamlit, and Visual Studio Code.
A custom portfolio assistant featuring real-time response streaming.

Never invent information about the creator.
Respond naturally and conversationally.
"""


# =========================================================
# MODELS
# =========================================================

class ChatRequest(BaseModel):
    message: str
    conversation: list[dict] = []


class SendEmailRequest(BaseModel):
    body: str | None = None
    draft: str | None = None


# =========================================================
# SESSION COOKIE
# =========================================================

@app.middleware("http")
async def session_middleware(request: Request, call_next):

    session_id = request.cookies.get("gmail_session")

    if not session_id:
        session_id = secrets.token_urlsafe(32)

    request.state.session_id = session_id

    response = await call_next(request)

    if not request.cookies.get("gmail_session"):
        response.set_cookie(
            key="gmail_session",
            value=session_id,
            httponly=True,
            secure=True,
            samesite="none",
            max_age=60 * 60 * 24 * 30
        )

    return response


# =========================================================
# DATABASE
# =========================================================

def get_db_connection():

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")

    from urllib.parse import urlparse

    parsed = urlparse(DATABASE_URL)

    host = parsed.hostname
    port = parsed.port or 5432
    user = parsed.username
    password = parsed.password
    database = parsed.path.lstrip("/")

    print("DB DEBUG HOST:", host)
    print("DB DEBUG PORT:", port)
    print("DB DEBUG USER:", user)
    print("DB DEBUG DATABASE:", database)

    return psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        sslmode="require"
    )


def init_database():

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS gmail_credentials (
            session_id TEXT PRIMARY KEY,
            token TEXT NOT NULL,
            refresh_token TEXT,
            token_uri TEXT NOT NULL,
            client_id TEXT NOT NULL,
            client_secret TEXT NOT NULL,
            scopes TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS email_classifications (
            session_id TEXT NOT NULL,
            email_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            classification TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (session_id, email_id)
        )
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("Database initialized.")


@app.on_event("startup")
def startup():

    try:
        print("DB CONNECTION TEST")

        conn = get_db_connection()
        conn.close()

        print("Database initialized.")
        init_database()

    except Exception as e:
        print("DATABASE ERROR:", repr(e))


# =========================================================
# GMAIL CREDENTIAL STORAGE
# =========================================================

def save_credentials(session_id, credentials):

    conn = get_db_connection()
    cur = conn.cursor()

    scopes = credentials.scopes or GMAIL_SCOPES

    cur.execute("""
        INSERT INTO gmail_credentials (
            session_id,
            token,
            refresh_token,
            token_uri,
            client_id,
            client_secret,
            scopes
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (session_id)
        DO UPDATE SET
            token = EXCLUDED.token,
            refresh_token = EXCLUDED.refresh_token,
            token_uri = EXCLUDED.token_uri,
            client_id = EXCLUDED.client_id,
            client_secret = EXCLUDED.client_secret,
            scopes = EXCLUDED.scopes
    """, (
        session_id,
        credentials.token,
        credentials.refresh_token,
        credentials.token_uri,
        credentials.client_id,
        credentials.client_secret,
        json.dumps(scopes)
    ))

    conn.commit()
    cur.close()
    conn.close()


def load_credentials(session_id):

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT *
        FROM gmail_credentials
        WHERE session_id = %s
    """, (session_id,))

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        return None

    try:
        scopes = json.loads(row["scopes"])
    except Exception:
        scopes = GMAIL_SCOPES

    credentials = Credentials(
        token=row["token"],
        refresh_token=row["refresh_token"],
        token_uri=row["token_uri"],
        client_id=row["client_id"],
        client_secret=row["client_secret"],
        scopes=scopes
    )

    return credentials


# =========================================================
# GMAIL SERVICE
# =========================================================

def get_gmail_service(request: Request):

    session_id = request.state.session_id

    credentials = load_credentials(session_id)

    if credentials is None:
        return None

    try:

        if credentials.expired and credentials.refresh_token:

            credentials.refresh(GoogleRequest())

            save_credentials(
                session_id,
                credentials
            )

        return build(
            "gmail",
            "v1",
            credentials=credentials
        )

    except Exception as e:

        print("GMAIL SERVICE ERROR:", repr(e))

        return None


# =========================================================
# GMAIL AUTH
# =========================================================

@app.get("/gmail/auth")
def gmail_auth(request: Request, response: Response):

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=GMAIL_SCOPES
    )

    flow.redirect_uri = GOOGLE_CALLBACK_URL

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )

    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=600
    )

    response.set_cookie(
        key="oauth_verifier",
        value=flow.code_verifier,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=600
    )

    response.headers["Location"] = authorization_url

    return {
        "authorization_url": authorization_url
    }


# =========================================================
# GMAIL CALLBACK
# =========================================================

@app.get("/gmail/callback")
def gmail_callback(
    request: Request,
    code: str,
    state: str
):

    saved_state = request.cookies.get("oauth_state")
    code_verifier = request.cookies.get("oauth_verifier")

    if not saved_state or saved_state != state:
        return {
            "error": "Invalid OAuth state"
        }

    if not code_verifier:
        return {
            "error": "Missing OAuth code verifier"
        }

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=GMAIL_SCOPES
    )

    flow.redirect_uri = GOOGLE_CALLBACK_URL
    flow.code_verifier = code_verifier

    flow.fetch_token(code=code)

    credentials = flow.credentials

    save_credentials(
        request.state.session_id,
        credentials
    )

    redirect = RedirectResponse(
        url=f"{FRONTEND_URL}/"
    )

    redirect.delete_cookie("oauth_state")
    redirect.delete_cookie("oauth_verifier")

    return redirect


# =========================================================
# GMAIL STATUS
# =========================================================

@app.get("/gmail/status")
def gmail_status(request: Request):

    credentials = load_credentials(
        request.state.session_id
    )

    if credentials is None:
        return {
            "connected": False,
            "email": None,
            "messages_total": 0,
            "threads_total": 0
        }

    try:

        service = get_gmail_service(request)

        if service is None:
            return {
                "connected": False,
                "email": None,
                "messages_total": 0,
                "threads_total": 0
            }

        profile = service.users().getProfile(
            userId="me"
        ).execute()

        return {
            "connected": True,
            "email": profile.get("emailAddress"),
            "messages_total": profile.get("messagesTotal", 0),
            "threads_total": profile.get("threadsTotal", 0)
        }

    except Exception as e:

        print("GMAIL STATUS ERROR:", repr(e))

        return {
            "connected": False,
            "email": None,
            "messages_total": 0,
            "threads_total": 0
        }


# =========================================================
# GET INBOX EMAILS
# =========================================================

@app.get("/gmail/inbox")
def get_inbox(
    request: Request,
    max_results: int = 20
):

    service = get_gmail_service(request)

    if service is None:
        return {
            "connected": False,
            "emails": []
        }

    max_results = max(
        1,
        min(max_results, 50)
    )

    results = service.users().messages().list(
        userId="me",
        maxResults=max_results,
        labelIds=["INBOX"]
    ).execute()

    messages = results.get(
        "messages",
        []
    )

    emails = []

    for message in messages:

        try:

            data = service.users().messages().get(
                userId="me",
                id=message["id"],
                format="metadata",
                metadataHeaders=[
                    "From",
                    "To",
                    "Subject",
                    "Date"
                ]
            ).execute()

            headers = data.get(
                "payload",
                {}
            ).get(
                "headers",
                []
            )

            sender = ""
            recipient = ""
            subject = ""
            date = ""

            for header in headers:

                name = header["name"].lower()

                if name == "from":
                    sender = header["value"]

                elif name == "to":
                    recipient = header["value"]

                elif name == "subject":
                    subject = header["value"]

                elif name == "date":
                    date = header["value"]

            emails.append({
                "id": message["id"],
                "from": sender,
                "to": recipient,
                "subject": subject,
                "date": date,
                "snippet": data.get("snippet", "")
            })

        except Exception as e:

            print(
                "INBOX EMAIL ERROR:",
                message["id"],
                repr(e)
            )

    return {
        "connected": True,
        "emails": emails
    }


# =========================================================
# GET ONE EMAIL
# =========================================================

def extract_email_body(payload):

    body = ""

    if "parts" in payload:

        for part in payload["parts"]:

            if part.get("mimeType") == "text/plain":

                body_data = part.get(
                    "body",
                    {}
                ).get("data")

                if body_data:

                    body = base64.urlsafe_b64decode(
                        body_data
                    ).decode(
                        "utf-8",
                        errors="ignore"
                    )

                break

            if part.get("parts"):

                nested = extract_email_body(
                    part
                )

                if nested:
                    return nested

    else:

        body_data = payload.get(
            "body",
            {}
        ).get("data")

        if body_data:

            body = base64.urlsafe_b64decode(
                body_data
            ).decode(
                "utf-8",
                errors="ignore"
            )

    return body


@app.get("/gmail/email/{email_id}")
def get_email(
    request: Request,
    email_id: str
):

    service = get_gmail_service(request)

    if service is None:
        return {
            "connected": False
        }

    data = service.users().messages().get(
        userId="me",
        id=email_id,
        format="full"
    ).execute()

    payload = data.get(
        "payload",
        {}
    )

    headers = payload.get(
        "headers",
        []
    )

    sender = ""
    recipient = ""
    subject = ""
    date = ""

    for header in headers:

        name = header["name"].lower()

        if name == "from":
            sender = header["value"]

        elif name == "to":
            recipient = header["value"]

        elif name == "subject":
            subject = header["value"]

        elif name == "date":
            date = header["value"]

    body = extract_email_body(payload)

    return {
        "connected": True,
        "email": {
            "id": email_id,
            "from": sender,
            "to": recipient,
            "subject": subject,
            "date": date,
            "body": body
        }
    }


# =========================================================
# HOME
# =========================================================

@app.get("/")
def home():

    return {
        "status": "AI agent backend is running!",
        "agent_enabled": agent_enabled
    }


# =========================================================
# AGENT ON
# =========================================================

@app.post("/agent/on")
def agent_on():

    global agent_enabled

    agent_enabled = True

    return {
        "agent_enabled": True
    }


# =========================================================
# AGENT OFF
# =========================================================

@app.post("/agent/off")
def agent_off():

    global agent_enabled

    agent_enabled = False

    return {
        "agent_enabled": False
    }


# =========================================================
# AGENT STATUS
# =========================================================

@app.get("/agent/status")
def agent_status():

    return {
        "agent_enabled": agent_enabled
    }


# =========================================================
# AI CHAT
# =========================================================

@app.post("/chat")
def chat(request: ChatRequest):

    if not agent_enabled:

        return {
            "response": None,
            "agent_enabled": False
        }

    if client is None:

        return {
            "response": "AI service is not configured.",
            "agent_enabled": True
        }

    messages = [
        {
            "role": "system",
            "content": SYSTEM_INSTRUCTION
        }
    ]

    messages.extend(
        request.conversation
    )

    messages.append({
        "role": "user",
        "content": request.message
    })

    try:

        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            temperature=0.6,
            max_completion_tokens=1024
        )

        return {
            "response": completion.choices[0].message.content,
            "agent_enabled": True
        }

    except Exception as e:

        print("CHAT ERROR:", repr(e))

        return {
            "response": "The AI service is temporarily unavailable.",
            "agent_enabled": True
        }


# =========================================================
# LOCAL EMAIL CLASSIFICATION
# =========================================================

def local_classification(
    sender,
    subject,
    snippet
):

    sender = (sender or "").lower()
    subject = (subject or "").lower()
    snippet = (snippet or "").lower()

    text = f"{sender} {subject} {snippet}"

    # SPAM
    spam_words = [
        "you have won",
        "winner",
        "claim your prize",
        "free money",
        "casino",
        "lottery",
        "get rich",
        "urgent opportunity",
        "viagra"
    ]

    if any(word in text for word in spam_words):
        return "Spam"


    # NEWSLETTERS
    newsletter_words = [
        "newsletter",
        "unsubscribe",
        "weekly digest",
        "daily digest",
        "monthly digest",
        "mailing list",
        "email preferences",
        "view this email in your browser"
    ]

    if any(word in text for word in newsletter_words):
        return "Newsletter"


    # PROMOTIONS
    promotion_words = [
        "sale",
        "discount",
        "off today",
        "limited time",
        "special offer",
        "coupon",
        "promo code",
        "promotion",
        "deal",
        "shop now",
        "buy now"
    ]

    if any(word in text for word in promotion_words):
        return "Promotion"


    # AUTOMATED NOTIFICATIONS
    notification_words = [
        "verification code",
        "authentication code",
        "sudo authentication",
        "password reset",
        "reset your password",
        "security alert",
        "verify your identity",
        "confirm your email",
        "confirm your account",
        "account verification",
        "login code",
        "one-time password",
        "otp",
        "deploy failed",
        "deploy succeeded",
        "is live:",
        "third-party oauth",
        "oauth application",
        "github notification",
        "gitlab notification",
        "render notification",
        "build failed",
        "build succeeded",
        "deployment"
    ]

    if any(word in text for word in notification_words):
        return "Notification"


    # IMPORTANT / REPLY SIGNALS
    important_words = [
        "urgent",
        "important",
        "action required",
        "please respond",
        "need your help",
        "can you help",
        "are you available",
        "let me know",
        "could you",
        "would you",
        "can you",
        "collaboration",
        "project inquiry",
        "project collaboration"
    ]

    if any(word in text for word in important_words):
        return "Reply Needed"


    # OBVIOUS HUMAN QUESTIONS
    if "?" in text:

        human_words = [
            "hi ",
            "hello",
            "hey ",
            "thanks",
            "thank you",
            "could you",
            "can you",
            "would you",
            "are you",
            "let me know"
        ]

        if any(word in text for word in human_words):
            return "Reply Needed"


    return None


# =========================================================
# CLASSIFICATION CACHE
# =========================================================

def make_email_fingerprint(
    sender,
    subject,
    snippet
):

    raw = (
        f"{sender.strip()}\n"
        f"{subject.strip()}\n"
        f"{snippet.strip()}"
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def get_cached_classification(
    session_id,
    email_id,
    fingerprint
):

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT classification
        FROM email_classifications
        WHERE session_id = %s
        AND email_id = %s
        AND fingerprint = %s
    """, (
        session_id,
        email_id,
        fingerprint
    ))

    row = cur.fetchone()

    cur.close()
    conn.close()

    if row:
        return row[0]

    return None


def save_classification(
    session_id,
    email_id,
    fingerprint,
    classification
):

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO email_classifications (
            session_id,
            email_id,
            fingerprint,
            classification,
            updated_at
        )
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (session_id, email_id)
        DO UPDATE SET
            fingerprint = EXCLUDED.fingerprint,
            classification = EXCLUDED.classification,
            updated_at = CURRENT_TIMESTAMP
    """, (
        session_id,
        email_id,
        fingerprint,
        classification
    ))

    conn.commit()

    cur.close()
    conn.close()


# =========================================================
# RATE LIMIT HANDLING
# =========================================================

def get_rate_limit_wait(error):

    message = str(error)

    match = re.search(
        r"try again in ([0-9.]+)s",
        message,
        re.IGNORECASE
    )

    if match:

        try:
            return float(
                match.group(1)
            )

        except Exception:
            pass

    return 5


# =========================================================
# AI CLASSIFIER
# =========================================================

def ai_classification(
    sender,
    subject,
    snippet
):

    global classifier_backoff_until

    if client is None:
        return "Other"

    now = time.time()

    if now < classifier_backoff_until:
        return "Other"


    classifier_prompt = """
Classify this email into exactly ONE category.

Categories:
Important
Reply Needed
Newsletter
Promotion
Notification
Spam
Other

Reply Needed = a real person likely expects a response.

Important = meaningful email that matters but does not clearly require a reply.

Newsletter = recurring informational mailing.

Promotion = marketing, sales, discounts, offers.

Notification = automated system/service notification.

Spam = obvious unwanted or suspicious bulk email.

Other = anything that does not clearly fit.

Return ONLY the category name.
"""


    user_prompt = f"""
From: {sender}
Subject: {subject}
Email: {snippet}
"""


    with classifier_lock:

        if time.time() < classifier_backoff_until:
            return "Other"

        try:

            completion = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {
                        "role": "system",
                        "content": classifier_prompt
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ],
                temperature=0,
                max_completion_tokens=20
            )

            result = (
                completion.choices[0]
                .message
                .content
                .strip()
            )

            result = result.replace(
                "*",
                ""
            ).strip()

            valid_categories = {
                "Important",
                "Reply Needed",
                "Newsletter",
                "Promotion",
                "Notification",
                "Spam",
                "Other"
            }

            if result in valid_categories:
                return result

            normalized = result.lower()

            for category in valid_categories:

                if category.lower() in normalized:
                    return category

            return "Other"


        except Exception as e:

            error_text = str(e)

            if "429" in error_text or "rate_limit" in error_text.lower():

                wait_time = get_rate_limit_wait(
                    e
                )

                classifier_backoff_until = (
                    time.time()
                    + min(
                        max(wait_time, 2),
                        30
                    )
                )

                print(
                    "CLASSIFIER RATE LIMIT - "
                    f"backing off for {wait_time:.2f}s"
                )

                return "Other"


            print(
                "CLASSIFIER ERROR:",
                repr(e)
            )

            return "Other"


# =========================================================
# MAIN CLASSIFIER
# =========================================================

def classify_email(
    session_id,
    email_id,
    sender,
    subject,
    snippet
):

    fingerprint = make_email_fingerprint(
        sender,
        subject,
        snippet
    )


    # -----------------------------------------------------
    # 1. DATABASE CACHE
    # -----------------------------------------------------

    cached = get_cached_classification(
        session_id,
        email_id,
        fingerprint
    )

    if cached:
        return cached


    # -----------------------------------------------------
    # 2. LOCAL CLASSIFICATION
    # -----------------------------------------------------

    local_result = local_classification(
        sender,
        subject,
        snippet
    )

    if local_result:

        save_classification(
            session_id,
            email_id,
            fingerprint,
            local_result
        )

        return local_result


    # -----------------------------------------------------
    # 3. AI CLASSIFICATION
    # -----------------------------------------------------

    result = ai_classification(
        sender,
        subject,
        snippet
    )


    # -----------------------------------------------------
    # 4. ONLY CACHE REAL AI RESULTS
    # -----------------------------------------------------

    if result != "Other" or time.time() >= classifier_backoff_until:

        save_classification(
            session_id,
            email_id,
            fingerprint,
            result
        )


    return result


# =========================================================
# FILTER ONE EMAIL
# =========================================================

@app.post("/gmail/filter/{email_id}")
def filter_email(
    request: Request,
    email_id: str
):

    service = get_gmail_service(request)

    if service is None:
        return {
            "connected": False
        }

    data = service.users().messages().get(
        userId="me",
        id=email_id,
        format="full"
    ).execute()

    headers = data.get(
        "payload",
        {}
    ).get(
        "headers",
        []
    )

    sender = ""
    subject = ""

    for header in headers:

        name = header["name"].lower()

        if name == "from":
            sender = header["value"]

        elif name == "subject":
            subject = header["value"]

    snippet = data.get(
        "snippet",
        ""
    )

    classification = classify_email(
        request.state.session_id,
        email_id,
        sender,
        subject,
        snippet
    )

    return {
        "email_id": email_id,
        "classification": classification
    }


# =========================================================
# FILTER ALL EMAILS
# =========================================================

@app.get("/gmail/filtered-emails")
def filtered_emails(
    request: Request,
    max_results: int = 20
):

    service = get_gmail_service(request)

    if service is None:
        return {
            "connected": False,
            "emails": []
        }

    max_results = max(
        1,
        min(max_results, 50)
    )

    try:

        results = service.users().messages().list(
            userId="me",
            maxResults=max_results,
            labelIds=["INBOX"]
        ).execute()

        messages = results.get(
            "messages",
            []
        )

        emails = []

        for message in messages:

            email_id = message["id"]

            try:

                data = service.users().messages().get(
                    userId="me",
                    id=email_id,
                    format="full"
                ).execute()

                headers = data.get(
                    "payload",
                    {}
                ).get(
                    "headers",
                    []
                )

                sender = ""
                subject = ""
                date = ""

                for header in headers:

                    name = header["name"].lower()

                    if name == "from":
                        sender = header["value"]

                    elif name == "subject":
                        subject = header["value"]

                    elif name == "date":
                        date = header["value"]

                snippet = data.get(
                    "snippet",
                    ""
                )

                classification = classify_email(
                    request.state.session_id,
                    email_id,
                    sender,
                    subject,
                    snippet
                )

                emails.append({
                    "id": email_id,
                    "from": sender,
                    "subject": subject,
                    "date": date,
                    "snippet": snippet,
                    "classification": classification
                })

            except Exception as e:

                print(
                    "FILTER EMAIL ERROR:",
                    email_id,
                    repr(e)
                )

        return {
            "connected": True,
            "emails": emails
        }

    except Exception as e:

        print(
            "FILTERED EMAILS ERROR:",
            repr(e)
        )

        return {
            "connected": True,
            "emails": [],
            "error": "Failed to load emails."
        }


# =========================================================
# GENERATE EMAIL DRAFT
# =========================================================

@app.get("/gmail/draft/{email_id}")
def generate_email_draft(
    request: Request,
    email_id: str
):

    service = get_gmail_service(request)

    if service is None:
        return {
            "connected": False,
            "error": "Gmail is not connected"
        }

    if client is None:
        return {
            "connected": True,
            "error": "AI service is not configured"
        }

    data = service.users().messages().get(
        userId="me",
        id=email_id,
        format="full"
    ).execute()

    payload = data.get(
        "payload",
        {}
    )

    headers = payload.get(
        "headers",
        []
    )

    sender = ""
    subject = ""

    for header in headers:

        name = header["name"].lower()

        if name == "from":
            sender = header["value"]

        elif name == "subject":
            subject = header["value"]

    body = extract_email_body(
        payload
    )

    try:

        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {
                    "role": "system",
                    "content": """
You write email replies for the creator of a portfolio.

Write a natural and helpful reply to the incoming email.

Portfolio information:

- School Admin Dashboard
  Built using Replit.
  A functional administrative login portal and dashboard data interface.

- School Landing Page
  Built using Visual Studio Code.
  A clean, fully responsive multi-page website built for a real school.

- My First AI Chatbox
  Built using Ziper AI.
  An AI chatbox providing information about the portfolio and projects.

- Custom Python AI Chatbot
  Built using Python, Streamlit, and Visual Studio Code.
  A custom portfolio assistant featuring real-time response streaming.

Rules:
- Answer the actual question.
- Sound like a real person.
- Be friendly.
- Be professional when appropriate.
- Keep the reply reasonably short.
- Do not invent information.
- Do not claim the creator has skills or experience that aren't listed.
- Do not mention that you are an AI.
- Do not include a subject line.
- Return ONLY the email reply.
"""
                },
                {
                    "role": "user",
                    "content": f"""
From:
{sender}

Subject:
{subject}

Email:
{body}
"""
                }
            ],
            temperature=0.6,
            max_completion_tokens=500
        )

        draft = (
            completion.choices[0]
            .message
            .content
            .strip()
        )

        return {
            "email_id": email_id,
            "from": sender,
            "subject": subject,
            "draft": draft
        }

    except Exception as e:

        print(
            "DRAFT ERROR:",
            repr(e)
        )

        return {
            "email_id": email_id,
            "error": "Failed to generate AI reply."
        }


# =========================================================
# SEND GMAIL REPLY
# =========================================================

@app.post("/gmail/send/{email_id}")
def send_gmail_reply(
    request: Request,
    email_id: str,
    email_request: SendEmailRequest
):

    draft = (
        email_request.body
        or email_request.draft
        or ""
    )

    if not draft.strip():

        return {
            "success": False,
            "message": "Draft cannot be empty."
        }

    service = get_gmail_service(request)

    if service is None:

        return {
            "success": False,
            "message": "Gmail is not connected."
        }

    try:

        original = service.users().messages().get(
            userId="me",
            id=email_id,
            format="metadata",
            metadataHeaders=[
                "From",
                "Subject"
            ]
        ).execute()

        headers = original.get(
            "payload",
            {}
        ).get(
            "headers",
            []
        )

        sender = ""
        subject = ""

        for header in headers:

            name = header["name"].lower()

            if name == "from":
                sender = header["value"]

            elif name == "subject":
                subject = header["value"]

        if not sender:

            return {
                "success": False,
                "message": "Could not find the sender."
            }

        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        html_draft = (
            draft
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )

        html_draft = re.sub(
            r"\*\*(.*?)\*\*",
            r"<strong>\1</strong>",
            html_draft
        )

        message = MIMEText(
            html_draft,
            "html"
        )

        message["To"] = sender
        message["Subject"] = subject

        encoded_message = base64.urlsafe_b64encode(
            message.as_bytes()
        ).decode()

        send_message = {
            "raw": encoded_message,
            "threadId": original.get(
                "threadId"
            )
        }

        sent = service.users().messages().send(
            userId="me",
            body=send_message
        ).execute()

        return {
            "success": True,
            "message": "Reply sent successfully.",
            "email_id": email_id,
            "sent_message_id": sent.get("id")
        }

    except Exception as e:

        print(
            "Gmail send error:",
            repr(e)
        )

        return {
            "success": False,
            "message": "Failed to send the email."
        }


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():

    return {
        "status": "healthy",
        "agent_enabled": agent_enabled
    }


# =========================================================
# DEBUG GOOGLE CONFIG
# =========================================================

@app.get("/debug/google-config")
def debug_google_config():

    return {
        "google_client_id_set": bool(
            GOOGLE_CLIENT_ID
        ),
        "google_client_secret_set": bool(
            GOOGLE_CLIENT_SECRET
        ),
        "callback_url": GOOGLE_CALLBACK_URL
    }
