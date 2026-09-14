from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from groq import Groq
from email.mime.text import MIMEText

import os
import base64
import re
import secrets
import json
import psycopg2

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest


# =========================================================
# APP
# =========================================================

app = FastAPI()


# =========================================================
# URLS
# =========================================================

FRONTEND_URL = "https://email-agent-panel.onrender.com"

BACKEND_URL = "https://my-portfolio-bot-test-2.onrender.com"

GOOGLE_CALLBACK_URL = (
    f"{BACKEND_URL}/gmail/callback"
)


# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# =========================================================
# ENVIRONMENT
# =========================================================

GROQ_API_KEY = os.environ.get(
    "GROQ_API_KEY",
    ""
).strip()

GOOGLE_CLIENT_ID = os.environ.get(
    "GOOGLE_CLIENT_ID",
    ""
).strip()

GOOGLE_CLIENT_SECRET = os.environ.get(
    "GOOGLE_CLIENT_SECRET",
    ""
).strip()

SUPABASE_DB_URL = os.environ.get(
    "SUPABASE_DB_URL",
    ""
).strip()


# =========================================================
# GROQ
# =========================================================

client = Groq(
    api_key=GROQ_API_KEY
)


# =========================================================
# GMAIL
# =========================================================

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose"
]


# =========================================================
# AGENT
# =========================================================

agent_enabled = True


# =========================================================
# DATABASE
# =========================================================

def get_db_connection():

    if not SUPABASE_DB_URL:

        print(
            "SUPABASE_DB_URL is not configured."
        )

        return None

    try:

        return psycopg2.connect(
            SUPABASE_DB_URL,
            sslmode="require"
        )

    except Exception as e:

        print(
            "Database connection error:",
            e
        )

        return None


def setup_database():

    connection = get_db_connection()

    if connection is None:
        return

    try:

        cursor = connection.cursor()

        cursor.execute("""
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

        connection.commit()

        cursor.close()
        connection.close()

        print(
            "Database ready."
        )

    except Exception as e:

        print(
            "Database setup error:",
            e
        )

        try:
            connection.close()
        except Exception:
            pass


# =========================================================
# SESSION
# =========================================================

def get_session_id(request: Request):

    return request.cookies.get(
        "gmail_session"
    )


def create_session_id():

    return secrets.token_urlsafe(
        32
    )


# =========================================================
# SAVE GMAIL CREDENTIALS
# =========================================================

def save_gmail_credentials(
    session_id,
    credentials
):

    if not session_id:
        return False

    connection = get_db_connection()

    if connection is None:
        return False

    try:

        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO gmail_credentials (
                session_id,
                token,
                refresh_token,
                token_uri,
                client_id,
                client_secret,
                scopes
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )

            ON CONFLICT (session_id)
            DO UPDATE SET
                token = EXCLUDED.token,
                refresh_token = COALESCE(
                    EXCLUDED.refresh_token,
                    gmail_credentials.refresh_token
                ),
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
            " ".join(
                credentials.scopes
                or GMAIL_SCOPES
            )
        ))

        connection.commit()

        cursor.close()
        connection.close()

        return True

    except Exception as e:

        print(
            "Could not save Gmail credentials:",
            e
        )

        try:
            connection.close()
        except Exception:
            pass

        return False


# =========================================================
# LOAD GMAIL CREDENTIALS
# =========================================================

def load_gmail_credentials(
    session_id
):

    if not session_id:
        return None

    connection = get_db_connection()

    if connection is None:
        return None

    try:

        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                token,
                refresh_token,
                token_uri,
                client_id,
                client_secret,
                scopes

            FROM gmail_credentials

            WHERE session_id = %s
        """, (
            session_id,
        ))

        row = cursor.fetchone()

        cursor.close()
        connection.close()

        if not row:
            return None

        (
            token,
            refresh_token,
            token_uri,
            client_id,
            client_secret,
            scopes
        ) = row

        credentials = Credentials(
            token=token,
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes.split()
        )

        if credentials.expired:

            if not credentials.refresh_token:
                return None

            credentials.refresh(
                GoogleRequest()
            )

            save_gmail_credentials(
                session_id,
                credentials
            )

        return credentials

    except Exception as e:

        print(
            "Could not load Gmail credentials:",
            e
        )

        try:
            connection.close()
        except Exception:
            pass

        return None


# =========================================================
# DELETE GMAIL CREDENTIALS
# =========================================================

def delete_gmail_credentials(
    session_id
):

    if not session_id:
        return False

    connection = get_db_connection()

    if connection is None:
        return False

    try:

        cursor = connection.cursor()

        cursor.execute("""
            DELETE FROM gmail_credentials

            WHERE session_id = %s
        """, (
            session_id,
        ))

        connection.commit()

        cursor.close()
        connection.close()

        return True

    except Exception as e:

        print(
            "Could not delete Gmail credentials:",
            e
        )

        try:
            connection.close()
        except Exception:
            pass

        return False


# =========================================================
# DATABASE STARTUP
# =========================================================

setup_database()


# =========================================================
# AI SYSTEM INSTRUCTION
# =========================================================

SYSTEM_INSTRUCTION = """
You are an AI assistant representing the creator of this portfolio.

The creator is BRUHH — a student, AI builder, web developer, and tech explorer.

Projects:

1. School Admin Dashboard - 2026
Built using Replit.
A functional administrative login portal and dashboard data interface.

2. School Landing Page - 2026
Built using Visual Studio Code.
A clean, fully responsive multi-page website built for a real school.

3. My First AI Chatbox - 2026
Built using Ziper AI.
An AI chatbox that provides information about this website and projects.

4. Custom Python AI Chatbot
Built using Python, Streamlit, and Visual Studio Code.
A custom portfolio assistant featuring real-time response streaming.

5. AI Email Assistant
An AI-powered email assistant that reads incoming emails, creates draft
replies, and lets the creator approve them before sending.

6. Cloud Live — Autonomous AI Social Media Pipeline
An autonomous cloud-based AI pipeline designed for minimal maintenance.

7. Project Showcase
A dedicated showcase website featuring the creator's projects.

8. Weather Forecast
A weather forecast website.

9. Electronic Lab
A Tinkercad-style electronics laboratory.

Rules:

- Use only the information provided above.
- Do not invent projects.
- Do not invent technologies.
- Do not invent experience.
- Respond naturally and conversationally.
"""


# =========================================================
# MODELS
# =========================================================

class ChatRequest(BaseModel):

    message: str

    conversation: list[dict] = []


class SendEmailRequest(BaseModel):

    draft: str


# =========================================================
# GMAIL SERVICE
# =========================================================

def get_gmail_service(
    request: Request
):

    session_id = get_session_id(
        request
    )

    if not session_id:
        return None

    credentials = load_gmail_credentials(
        session_id
    )

    if credentials is None:
        return None

    try:

        if credentials.expired:

            if not credentials.refresh_token:
                return None

            credentials.refresh(
                GoogleRequest()
            )

            save_gmail_credentials(
                session_id,
                credentials
            )

        return build(
            "gmail",
            "v1",
            credentials=credentials
        )

    except Exception as e:

        print(
            "Gmail service error:",
            e
        )

        return None


# =========================================================
# GMAIL AUTH
# =========================================================

@app.get("/gmail/auth")
def gmail_auth():

    try:

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": (
                        "https://accounts.google.com/"
                        "o/oauth2/auth"
                    ),
                    "token_uri": (
                        "https://oauth2.googleapis.com/token"
                    ),
                    "redirect_uris": [
                        GOOGLE_CALLBACK_URL
                    ]
                }
            },
            scopes=GMAIL_SCOPES
        )

        flow.redirect_uri = (
            GOOGLE_CALLBACK_URL
        )

        authorization_url, state = (
            flow.authorization_url(
                access_type="offline",
                include_granted_scopes="true",
                prompt="consent"
            )
        )

        response = Response(
            content=authorization_url,
            media_type="text/plain"
        )

        # OAuth state
        response.set_cookie(
            key="oauth_state",
            value=state,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=600,
            path="/"
        )

        # PKCE verifier
        if flow.code_verifier:

            response.set_cookie(
                key="oauth_verifier",
                value=flow.code_verifier,
                httponly=True,
                secure=True,
                samesite="lax",
                max_age=600,
                path="/"
            )

        # The frontend expects JSON.
        response = Response(
            content=(
                '{"authorization_url": '
                f'"{authorization_url.replace(chr(34), chr(92) + chr(34))}"'
                '}'
            ),
            media_type="application/json"
        )

        response.set_cookie(
            key="oauth_state",
            value=state,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=600,
            path="/"
        )

        if flow.code_verifier:

            response.set_cookie(
                key="oauth_verifier",
                value=flow.code_verifier,
                httponly=True,
                secure=True,
                samesite="lax",
                max_age=600,
                path="/"
            )

        return response

    except Exception as e:

        print(
            "Gmail auth error:",
            e
        )

        return {
            "error": (
                "Could not start Gmail authentication."
            )
        }


# =========================================================
# GMAIL CALLBACK
# =========================================================

@app.get("/gmail/callback")
def gmail_callback(
    request: Request
):

    saved_state = request.cookies.get(
        "oauth_state"
    )

    code_verifier = request.cookies.get(
        "oauth_verifier"
    )

    returned_state = request.query_params.get(
        "state"
    )

    code = request.query_params.get(
        "code"
    )

    error = request.query_params.get(
        "error"
    )

    # Google cancelled/denied authorization
    if error:

        return Response(
            content=(
                f"Google authorization failed: {error}"
            ),
            status_code=400
        )

    # Check state
    if (
        not saved_state
        or not returned_state
        or saved_state != returned_state
    ):

        print(
            "OAuth state mismatch."
        )

        print(
            "Saved state exists:",
            bool(saved_state)
        )

        print(
            "Returned state exists:",
            bool(returned_state)
        )

        return Response(
            content="Invalid OAuth state",
            status_code=400
        )

    if not code:

        return Response(
            content="Missing OAuth authorization code",
            status_code=400
        )

    if not code_verifier:

        return Response(
            content="Missing OAuth code verifier",
            status_code=400
        )

    try:

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": (
                        "https://accounts.google.com/"
                        "o/oauth2/auth"
                    ),
                    "token_uri": (
                        "https://oauth2.googleapis.com/token"
                    ),
                    "redirect_uris": [
                        GOOGLE_CALLBACK_URL
                    ]
                }
            },
            scopes=GMAIL_SCOPES,
            state=saved_state
        )

        flow.redirect_uri = (
            GOOGLE_CALLBACK_URL
        )

        flow.code_verifier = code_verifier

        # Use the complete callback URL.
        authorization_response = str(
            request.url
        )

        flow.fetch_token(
            authorization_response=authorization_response
        )

        credentials = flow.credentials

    except Exception as e:

        print(
            "OAuth token error:",
            e
        )

        return Response(
            content=(
                "Could not complete Gmail authentication."
            ),
            status_code=400
        )

    # Get browser session
    session_id = get_session_id(
        request
    )

    # Create a new session if this browser
    # does not already have one.
    if not session_id:

        session_id = create_session_id()

    # Save credentials ONLY for this session.
    saved = save_gmail_credentials(
        session_id,
        credentials
    )

    if not saved:

        return Response(
            content=(
                "Could not save Gmail connection."
            ),
            status_code=500
        )

    # Redirect back to frontend.
    redirect = RedirectResponse(
        url=FRONTEND_URL,
        status_code=303
    )

    # Gmail session
    redirect.set_cookie(
        key="gmail_session",
        value=session_id,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
        path="/"
    )

    # Delete temporary OAuth cookies.
    redirect.delete_cookie(
        "oauth_state",
        path="/"
    )

    redirect.delete_cookie(
        "oauth_verifier",
        path="/"
    )

    return redirect


# =========================================================
# GMAIL STATUS
# =========================================================

@app.get("/gmail/status")
def gmail_status(
    request: Request
):

    session_id = get_session_id(
        request
    )

    if not session_id:

        return {
            "connected": False
        }

    credentials = load_gmail_credentials(
        session_id
    )

    if credentials is None:

        return {
            "connected": False
        }

    try:

        service = build(
            "gmail",
            "v1",
            credentials=credentials
        )

        profile = (
            service
            .users()
            .getProfile(userId="me")
            .execute()
        )

        return {
            "connected": True,
            "email": profile.get(
                "emailAddress"
            )
        }

    except Exception as e:

        print(
            "Gmail status verification failed:",
            e
        )

        return {
            "connected": False
        }


# =========================================================
# GMAIL DISCONNECT
# =========================================================

@app.post("/gmail/disconnect")
def gmail_disconnect(
    request: Request,
    response: Response
):

    session_id = get_session_id(
        request
    )

    success = delete_gmail_credentials(
        session_id
    )

    response.delete_cookie(
        "gmail_session",
        path="/"
    )

    return {
        "success": success,
        "connected": False
    }


# =========================================================
# GET INBOX
# =========================================================

@app.get("/gmail/emails")
def get_emails(
    request: Request
):

    service = get_gmail_service(
        request
    )

    if service is None:

        return {
            "connected": False,
            "emails": []
        }

    try:

        results = (
            service
            .users()
            .messages()
            .list(
                userId="me",
                maxResults=10,
                labelIds=["INBOX"]
            )
            .execute()
        )

        messages = results.get(
            "messages",
            []
        )

        emails = []

        for message in messages:

            data = (
                service
                .users()
                .messages()
                .get(
                    userId="me",
                    id=message["id"],
                    format="metadata",
                    metadataHeaders=[
                        "From",
                        "To",
                        "Subject",
                        "Date"
                    ]
                )
                .execute()
            )

            headers = (
                data
                .get("payload", {})
                .get("headers", [])
            )

            sender = ""
            recipient = ""
            subject = ""
            date = ""

            for header in headers:

                name = header[
                    "name"
                ].lower()

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
                "sender": sender,
                "to": recipient,
                "subject": subject,
                "date": date,
                "snippet": data.get(
                    "snippet",
                    ""
                )
            })

        return {
            "connected": True,
            "emails": emails
        }

    except Exception as e:

        print(
            "Gmail inbox error:",
            e
        )

        return {
            "connected": False,
            "emails": []
        }


# =========================================================
# GET ONE EMAIL
# =========================================================

@app.get("/gmail/email/{email_id}")
def get_email(
    email_id: str,
    request: Request
):

    service = get_gmail_service(
        request
    )

    if service is None:

        return {
            "connected": False
        }

    try:

        data = (
            service
            .users()
            .messages()
            .get(
                userId="me",
                id=email_id,
                format="full"
            )
            .execute()
        )

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

            name = header[
                "name"
            ].lower()

            if name == "from":
                sender = header["value"]

            elif name == "to":
                recipient = header["value"]

            elif name == "subject":
                subject = header["value"]

            elif name == "date":
                date = header["value"]

        body = extract_email_body(
            payload
        )

        return {
            "connected": True,
            "email": {
                "id": email_id,
                "from": sender,
                "sender": sender,
                "to": recipient,
                "subject": subject,
                "date": date,
                "body": body
            }
        }

    except Exception as e:

        print(
            "Get email error:",
            e
        )

        return {
            "connected": False
        }


# =========================================================
# EMAIL BODY HELPER
# =========================================================

def extract_email_body(
    payload
):

    # Direct body
    body_data = (
        payload
        .get("body", {})
        .get("data")
    )

    if body_data:

        try:

            return base64.urlsafe_b64decode(
                body_data
            ).decode(
                "utf-8",
                errors="ignore"
            )

        except Exception:
            pass

    # Multipart email
    parts = payload.get(
        "parts",
        []
    )

    for part in parts:

        mime_type = part.get(
            "mimeType",
            ""
        )

        if mime_type == "text/plain":

            part_data = (
                part
                .get("body", {})
                .get("data")
            )

            if part_data:

                try:

                    return base64.urlsafe_b64decode(
                        part_data
                    ).decode(
                        "utf-8",
                        errors="ignore"
                    )

                except Exception:
                    pass

        # Nested multipart
        nested_parts = part.get(
            "parts"
        )

        if nested_parts:

            result = extract_email_body(
                part
            )

            if result:
                return result

    return ""


# =========================================================
# HOME
# =========================================================

@app.get("/")
def home():

    return {
        "status": (
            "AI agent backend is running!"
        ),
        "agent_enabled": agent_enabled,
        "enabled": agent_enabled
    }


# =========================================================
# AGENT ON
# =========================================================

@app.post("/agent/on")
def agent_on():

    global agent_enabled

    agent_enabled = True

    return {
        "agent_enabled": True,
        "enabled": True
    }


# =========================================================
# AGENT OFF
# =========================================================

@app.post("/agent/off")
def agent_off():

    global agent_enabled

    agent_enabled = False

    return {
        "agent_enabled": False,
        "enabled": False
    }


# =========================================================
# AGENT STATUS
# =========================================================

@app.get("/agent/status")
def agent_status():

    return {
        "agent_enabled": agent_enabled,
        "enabled": agent_enabled
    }


# =========================================================
# AI CHAT
# =========================================================

@app.post("/chat")
def chat(
    request: ChatRequest
):

    if not agent_enabled:

        return {
            "response": None,
            "agent_enabled": False,
            "enabled": False
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

        completion = (
            client
            .chat
            .completions
            .create(
                model="openai/gpt-oss-20b",
                messages=messages,
                temperature=0.6,
                max_completion_tokens=1024
            )
        )

        return {
            "response": (
                completion
                .choices[0]
                .message
                .content
            ),
            "agent_enabled": True,
            "enabled": True
        }

    except Exception as e:

        print(
            "Chat error:",
            e
        )

        return {
            "response": (
                "Sorry, I couldn't process that."
            ),
            "agent_enabled": True,
            "enabled": True
        }


# =========================================================
# EMAIL CLASSIFIER
# =========================================================

def classify_email(
    sender,
    subject,
    snippet
):

    sender = sender.lower()
    subject = subject.lower()
    snippet = snippet.lower()

    text = (
        f"{sender} "
        f"{subject} "
        f"{snippet}"
    )

    ignore_words = [
        "verification code",
        "authentication code",
        "sudo authentication",
        "sudo email verification",
        "password reset",
        "reset your password",
        "security alert",
        "verify your identity",
        "confirm your email",
        "confirm your account",
        "account verification",
        "login code",
        "one-time password",
        "unsubscribe",
        "newsletter",
        "deploy failed",
        "deploy succeeded",
        "is live:",
        "streaming",
        "third-party oauth",
        "oauth application"
    ]

    for word in ignore_words:

        if word in text:
            return "IGNORE"

    portfolio_words = [
        "portfolio",
        "projects",
        "project",
        "developer",
        "website",
        "built",
        "worked on",
        "your work"
    ]

    question_words = [
        "?",
        "what",
        "which",
        "how",
        "can you",
        "could you",
        "tell me",
        "would you"
    ]

    has_portfolio_topic = any(
        word in text
        for word in portfolio_words
    )

    has_question = any(
        word in text
        for word in question_words
    )

    if (
        has_portfolio_topic
        and has_question
    ):

        return "PROCESS"

    collaboration_words = [
        "work with you",
        "work together",
        "collaborate",
        "collaboration",
        "interested in working",
        "would like to work",
        "want to work",
        "project opportunity",
        "business opportunity",
        "partnership",
        "partner with you",
        "join our team",
        "work on a project",
        "hire you",
        "hiring"
    ]

    if any(
        word in text
        for word in collaboration_words
    ):

        return "PROCESS"

    try:

        completion = (
            client
            .chat
            .completions
            .create(
                model="openai/gpt-oss-20b",
                messages=[
                    {
                        "role": "system",
                        "content": """
Classify this email.

Return ONLY:

PROCESS

or

IGNORE

PROCESS:
- Genuine message from a person
- Personal conversation
- Professional inquiry
- Genuine question
- Project inquiry
- Collaboration inquiry
- Portfolio question
- Someone expecting a personal response
- Job or project opportunity
- Partnership or business opportunity

IGNORE:
- Automated emails
- Verification emails
- Security emails
- Password emails
- Login codes
- Account confirmation
- GitHub notifications
- GitLab notifications
- Render notifications
- Streaming notifications
- Newsletters
- Marketing
- Promotions
- Spam
- Mass emails

Return ONLY PROCESS or IGNORE.
"""
                    },
                    {
                        "role": "user",
                        "content": f"""
From: {sender}

Subject: {subject}

Email:
{snippet}
"""
                    }
                ],
                temperature=0,
                max_completion_tokens=10
            )
        )

        result = (
            completion
            .choices[0]
            .message
            .content
            .strip()
            .upper()
        )

        if result == "PROCESS":
            return "PROCESS"

    except Exception as e:

        print(
            "Classifier error:",
            e
        )

    return "IGNORE"


# =========================================================
# FILTER EMAILS
# =========================================================

@app.get("/gmail/filtered-emails")
def filtered_emails(
    request: Request
):

    service = get_gmail_service(
        request
    )

    if service is None:

        return {
            "connected": False,
            "emails": []
        }

    try:

        results = (
            service
            .users()
            .messages()
            .list(
                userId="me",
                maxResults=10,
                labelIds=["INBOX"]
            )
            .execute()
        )

        messages = results.get(
            "messages",
            []
        )

        emails = []

        for message in messages:

            email_id = message[
                "id"
            ]

            data = (
                service
                .users()
                .messages()
                .get(
                    userId="me",
                    id=email_id,
                    format="full"
                )
                .execute()
            )

            headers = (
                data
                .get("payload", {})
                .get("headers", [])
            )

            sender = ""
            subject = ""

            for header in headers:

                name = header[
                    "name"
                ].lower()

                if name == "from":
                    sender = header[
                        "value"
                    ]

                elif name == "subject":
                    subject = header[
                        "value"
                    ]

            snippet = data.get(
                "snippet",
                ""
            )

            classification = classify_email(
                sender,
                subject,
                snippet
            )

            emails.append({
                "id": email_id,

                "from": sender,

                "sender": sender,

                "subject": subject,

                "snippet": snippet,

                "classification": classification,

                # Used by frontend
                "action": classification
            })

        return {
            "connected": True,
            "emails": emails
        }

    except Exception as e:

        print(
            "Filtered email error:",
            e
        )

        return {
            "connected": False,
            "emails": []
        }


# =========================================================
# GENERATE EMAIL DRAFT
# =========================================================

@app.post("/gmail/draft/{email_id}")
def generate_email_draft(
    email_id: str,
    request: Request
):

    service = get_gmail_service(
        request
    )

    if service is None:

        return {
            "connected": False,
            "error": (
                "Gmail is not connected."
            )
        }

    try:

        data = (
            service
            .users()
            .messages()
            .get(
                userId="me",
                id=email_id,
                format="full"
            )
            .execute()
        )

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

            name = header[
                "name"
            ].lower()

            if name == "from":
                sender = header[
                    "value"
                ]

            elif name == "subject":
                subject = header[
                    "value"
                ]

        body = extract_email_body(
            payload
        )

        completion = (
            client
            .chat
            .completions
            .create(
                model="openai/gpt-oss-20b",
                messages=[
                    {
                        "role": "system",
                        "content": """
You write email replies for the creator of a portfolio.

Write a natural and helpful reply.

The creator is BRUHH — a student, AI builder,
web developer, and tech explorer.

Rules:

- Answer the actual question.
- Sound like a real person.
- Be friendly.
- Be professional when appropriate.
- Keep the reply reasonably short.
- Do not invent information.
- Do not claim skills or experience not provided.
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
        )

        draft = (
            completion
            .choices[0]
            .message
            .content
            .strip()
        )

        return {
            "email_id": email_id,
            "from": sender,
            "sender": sender,
            "subject": subject,
            "draft": draft
        }

    except Exception as e:

        print(
            "Draft generation error:",
            e
        )

        return {
            "connected": True,
            "error": (
                "Could not generate draft."
            )
        }


# =========================================================
# SEND EMAIL
# =========================================================

@app.post("/gmail/send/{email_id}")
def send_gmail_reply(
    email_id: str,
    request: SendEmailRequest,
    http_request: Request
):

    draft = request.draft

    service = get_gmail_service(
        http_request
    )

    if service is None:

        return {
            "success": False,
            "message": (
                "Gmail is not connected."
            )
        }

    if not draft.strip():

        return {
            "success": False,
            "message": (
                "Draft cannot be empty."
            )
        }

    try:

        original = (
            service
            .users()
            .messages()
            .get(
                userId="me",
                id=email_id,
                format="metadata",
                metadataHeaders=[
                    "From",
                    "Subject"
                ]
            )
            .execute()
        )

        headers = (
            original
            .get("payload", {})
            .get("headers", [])
        )

        sender = ""
        subject = ""

        for header in headers:

            name = header[
                "name"
            ].lower()

            if name == "from":

                sender = header[
                    "value"
                ]

            elif name == "subject":

                subject = header[
                    "value"
                ]

        if not sender:

            return {
                "success": False,
                "message": (
                    "Could not find the sender."
                )
            }

        if not subject.lower().startswith(
            "re:"
        ):

            subject = (
                f"Re: {subject}"
            )

        # Escape HTML safely.
        html_draft = (
            draft
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#039;")
            .replace("\n", "<br>")
        )

        # Optional markdown bold
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

        encoded_message = (
            base64
            .urlsafe_b64encode(
                message.as_bytes()
            )
            .decode()
        )

        send_message = {
            "raw": encoded_message,
            "threadId": original.get(
                "threadId"
            )
        }

        sent = (
            service
            .users()
            .messages()
            .send(
                userId="me",
                body=send_message
            )
            .execute()
        )

        return {
            "success": True,
            "message": (
                "Reply sent successfully."
            ),
            "email_id": email_id,
            "sent_message_id": sent.get(
                "id"
            )
        }

    except Exception as e:

        print(
            "Gmail send error:",
            e
        )

        return {
            "success": False,
            "message": (
                "Failed to send the email."
            )
        }
