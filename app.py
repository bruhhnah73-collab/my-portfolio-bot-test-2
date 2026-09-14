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

FRONTEND_URL = (
    "https://email-agent-panel.onrender.com"
)

BACKEND_URL = (
    "https://my-portfolio-bot-test-2.onrender.com"
)

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
# ENVIRONMENT VARIABLES
# =========================================================

GROQ_API_KEY = os.getenv(
    "GROQ_API_KEY"
)

DATABASE_URL = os.getenv(
    "DATABASE_URL"
)

GOOGLE_CLIENT_ID = os.getenv(
    "GOOGLE_CLIENT_ID"
)

GOOGLE_CLIENT_SECRET = os.getenv(
    "GOOGLE_CLIENT_SECRET"
)


# =========================================================
# GROQ
# =========================================================

groq_client = None

if GROQ_API_KEY:

    groq_client = Groq(
        api_key=GROQ_API_KEY
    )


# =========================================================
# GMAIL SCOPES
# =========================================================

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify"
]


# =========================================================
# AGENT STATE
# =========================================================

agent_enabled = True


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_db_connection():

    if not DATABASE_URL:
        print(
            "DATABASE_URL is missing."
        )
        return None

    try:

        return psycopg2.connect(
            DATABASE_URL
        )

    except Exception as e:

        print(
            "DATABASE CONNECTION ERROR:",
            repr(e)
        )

        return None


# =========================================================
# DATABASE SETUP
# =========================================================

def init_database():

    conn = get_db_connection()

    if not conn:
        return

    try:

        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gmail_credentials (
                session_id TEXT PRIMARY KEY,
                token TEXT NOT NULL,
                refresh_token TEXT,
                token_uri TEXT NOT NULL,
                client_id TEXT NOT NULL,
                client_secret TEXT NOT NULL,
                scopes TEXT NOT NULL
            )
            """
        )

        conn.commit()

        cur.close()
        conn.close()

        print(
            "Database initialized."
        )

    except Exception as e:

        print(
            "DATABASE INIT ERROR:",
            repr(e)
        )

        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass


@app.on_event("startup")
def startup_event():

    init_database()


# =========================================================
# SESSION HELPERS
# =========================================================

def create_session_id():

    return secrets.token_urlsafe(
        32
    )


def get_session_id(
    request: Request
):

    return request.cookies.get(
        "gmail_session"
    )


# =========================================================
# SAVE GMAIL CREDENTIALS
# =========================================================

def save_gmail_credentials(
    session_id,
    credentials
):

    conn = None

    try:

        conn = get_db_connection()

        if not conn:

            print(
                "SAVE GMAIL CREDENTIALS ERROR: "
                "Could not connect to database."
            )

            return False

        cur = conn.cursor()

        token = credentials.token

        refresh_token = (
            credentials.refresh_token
        )

        token_uri = (
            credentials.token_uri
        )

        client_id = (
            credentials.client_id
        )

        client_secret = (
            credentials.client_secret
        )

        scopes = json.dumps(
            credentials.scopes
            or GMAIL_SCOPES
        )

        cur.execute(
            """
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
                refresh_token = EXCLUDED.refresh_token,
                token_uri = EXCLUDED.token_uri,
                client_id = EXCLUDED.client_id,
                client_secret = EXCLUDED.client_secret,
                scopes = EXCLUDED.scopes
            """,
            (
                session_id,
                token,
                refresh_token,
                token_uri,
                client_id,
                client_secret,
                scopes
            )
        )

        conn.commit()

        cur.close()
        conn.close()

        print(
            "Gmail credentials saved successfully "
            "for session:",
            session_id
        )

        return True

    except Exception as e:

        print(
            "SAVE GMAIL CREDENTIALS ERROR:",
            repr(e)
        )

        if conn:

            try:
                conn.rollback()
                conn.close()
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

    conn = get_db_connection()

    if not conn:
        return None

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                token,
                refresh_token,
                token_uri,
                client_id,
                client_secret,
                scopes
            FROM gmail_credentials
            WHERE session_id = %s
            """,
            (
                session_id,
            )
        )

        row = cur.fetchone()

        cur.close()
        conn.close()

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

        try:

            scopes = json.loads(
                scopes
            )

        except Exception:

            scopes = GMAIL_SCOPES

        credentials = Credentials(
            token=token,
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes
        )

        # Refresh expired credentials
        if credentials.expired and credentials.refresh_token:

            try:

                credentials.refresh(
                    GoogleRequest()
                )

                save_gmail_credentials(
                    session_id,
                    credentials
                )

            except Exception as e:

                print(
                    "TOKEN REFRESH ERROR:",
                    repr(e)
                )

        return credentials

    except Exception as e:

        print(
            "LOAD GMAIL CREDENTIALS ERROR:",
            repr(e)
        )

        try:
            conn.close()
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

    conn = get_db_connection()

    if not conn:
        return False

    try:

        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM gmail_credentials
            WHERE session_id = %s
            """,
            (
                session_id,
            )
        )

        conn.commit()

        cur.close()
        conn.close()

        return True

    except Exception as e:

        print(
            "DELETE GMAIL CREDENTIALS ERROR:",
            repr(e)
        )

        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass

        return False


# =========================================================
# GOOGLE FLOW
# =========================================================

def create_google_flow(
    state=None
):

    config = {

        "web": {

            "client_id":
                GOOGLE_CLIENT_ID,

            "client_secret":
                GOOGLE_CLIENT_SECRET,

            "auth_uri":
                "https://accounts.google.com/"
                "o/oauth2/auth",

            "token_uri":
                "https://oauth2.googleapis.com/token",

            "redirect_uris": [
                GOOGLE_CALLBACK_URL
            ]
        }
    }

    flow = Flow.from_client_config(
        config,
        scopes=GMAIL_SCOPES,
        state=state
    )

    flow.redirect_uri = (
        GOOGLE_CALLBACK_URL
    )

    return flow


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

    if not credentials:
        return None

    try:

        return build(
            "gmail",
            "v1",
            credentials=credentials
        )

    except Exception as e:

        print(
            "GMAIL SERVICE ERROR:",
            repr(e)
        )

        return None


# =========================================================
# SYSTEM INSTRUCTION
# =========================================================

SYSTEM_INSTRUCTION = """
You are an AI email assistant.

Your job is to help the user understand,
classify, draft, and respond to emails.

Be concise, professional, and useful.

Never invent facts that are not present
in the email or conversation.

When drafting replies:
- Be natural.
- Be polite.
- Match the context.
- Do not add unnecessary information.
"""


# =========================================================
# MODELS
# =========================================================

class ChatRequest(BaseModel):

    message: str

    history: list = []


class DraftRequest(BaseModel):

    instructions: str = ""


# =========================================================
# HOME
# =========================================================

@app.get("/")
def home():

    return {
        "status": "online",
        "service": "Email AI Agent",
        "gmail": True
    }


# =========================================================
# AGENT STATUS
# =========================================================

@app.get("/agent/status")
def agent_status():

    return {
        "enabled": agent_enabled,
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
        "success": True,
        "enabled": True,
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
        "success": True,
        "enabled": False,
        "agent_enabled": False
    }


# =========================================================
# GMAIL AUTH
# =========================================================

@app.get("/gmail/auth")
def gmail_auth():

    try:

        flow = create_google_flow()

        authorization_url, state = (
            flow.authorization_url(
                access_type="offline",
                include_granted_scopes="true",
                prompt="consent"
            )
        )

        response = Response(
            content=json.dumps(
                {
                    "authorization_url":
                        authorization_url
                }
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
            "GMAIL AUTH ERROR:",
            repr(e)
        )

        return Response(
            content=json.dumps(
                {
                    "error":
                        "Could not start Gmail authentication."
                }
            ),
            media_type="application/json",
            status_code=500
        )


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

    returned_state = (
        request.query_params.get(
            "state"
        )
    )

    code = (
        request.query_params.get(
            "code"
        )
    )

    error = (
        request.query_params.get(
            "error"
        )
    )

    # -----------------------------------------------------
    # GOOGLE ERROR
    # -----------------------------------------------------

    if error:

        return Response(
            content=(
                f"Google authorization failed: "
                f"{error}"
            ),
            status_code=400
        )

    # -----------------------------------------------------
    # STATE CHECK
    # -----------------------------------------------------

    if (
        not saved_state
        or not returned_state
        or saved_state != returned_state
    ):

        return Response(
            content="Invalid OAuth state",
            status_code=400
        )

    # -----------------------------------------------------
    # CODE CHECK
    # -----------------------------------------------------

    if not code:

        return Response(
            content=(
                "Missing OAuth authorization code"
            ),
            status_code=400
        )

    # -----------------------------------------------------
    # VERIFIER CHECK
    # -----------------------------------------------------

    if not code_verifier:

        return Response(
            content=(
                "Missing OAuth code verifier"
            ),
            status_code=400
        )

    # -----------------------------------------------------
    # EXCHANGE CODE FOR TOKEN
    # -----------------------------------------------------

   

    try:

        flow = create_google_flow(
            state=saved_state
        )

        flow.redirect_uri = (
            GOOGLE_CALLBACK_URL
        )

        flow.code_verifier = (
            code_verifier
        )

        flow.fetch_token(
            authorization_response=
                str(request.url)
        )

        credentials = (
            flow.credentials
        )

    except Exception as e:

        print(
            "OAUTH TOKEN ERROR:",
            repr(e)
        )

        return Response(
            content=(
                f"OAUTH TOKEN ERROR: {repr(e)}"
            ),
            status_code=400
        )
    # -----------------------------------------------------
    # SESSION
    # -----------------------------------------------------

    session_id = get_session_id(
        request
    )

    if not session_id:

        session_id = create_session_id()

    # -----------------------------------------------------
    # SAVE
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # REDIRECT
    # -----------------------------------------------------

    redirect = RedirectResponse(
        url=FRONTEND_URL,
        status_code=303
    )

    redirect.set_cookie(
        key="gmail_session",
        value=session_id,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
        path="/"
    )

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

    service = get_gmail_service(
        request
    )

    if not service:

        return {
            "connected": False
        }

    try:

        profile = (
            service.users()
            .getProfile(
                userId="me"
            )
            .execute()
        )

        return {
            "connected": True,
            "email":
                profile.get("emailAddress"),
            "messages_total":
                profile.get("messagesTotal"),
            "threads_total":
                profile.get("threadsTotal")
        }

    except Exception as e:

        print(
            "GMAIL STATUS ERROR:",
            repr(e)
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

    if session_id:

        delete_gmail_credentials(
            session_id
        )

    response.delete_cookie(
        "gmail_session",
        path="/"
    )

    return {
        "success": True,
        "connected": False
    }


# =========================================================
# GET INBOX
# =========================================================

@app.get("/gmail/inbox")
def gmail_inbox(
    request: Request,
    max_results: int = 20
):

    service = get_gmail_service(
        request
    )

    if not service:

        return {
            "connected": False,
            "emails": []
        }

    try:

        result = (
            service.users()
            .messages()
            .list(
                userId="me",
                labelIds=["INBOX"],
                maxResults=max_results
            )
            .execute()
        )

        messages = result.get(
            "messages",
            []
        )

        emails = []

        for message in messages:

            try:

                data = (
                    service.users()
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
                    data.get(
                        "payload",
                        {}
                    )
                    .get(
                        "headers",
                        []
                    )
                )

                header_map = {}

                for header in headers:

                    header_map[
                        header["name"].lower()
                    ] = header["value"]

                emails.append(
                    {
                        "id":
                            data.get("id"),

                        "threadId":
                            data.get(
                                "threadId"
                            ),

                        "sender":
                            header_map.get(
                                "from",
                                ""
                            ),

                        "from":
                            header_map.get(
                                "from",
                                ""
                            ),

                        "to":
                            header_map.get(
                                "to",
                                ""
                            ),

                        "subject":
                            header_map.get(
                                "subject",
                                "(No subject)"
                            ),

                        "date":
                            header_map.get(
                                "date",
                                ""
                            ),

                        "snippet":
                            data.get(
                                "snippet",
                                ""
                            )
                    }
                )

            except Exception as e:

                print(
                    "EMAIL READ ERROR:",
                    repr(e)
                )

        return {
            "connected": True,
            "emails": emails
        }

    except Exception as e:

        print(
            "INBOX ERROR:",
            repr(e)
        )

        return {
            "connected": True,
            "emails": [],
            "error": str(e)
        }


# =========================================================
# EXTRACT EMAIL BODY
# =========================================================

def extract_email_body(
    payload
):

    if not payload:
        return ""

    mime_type = payload.get(
        "mimeType",
        ""
    )

    body = payload.get(
        "body",
        {}
    )

    data = body.get(
        "data"
    )

    if data:

        try:

            decoded = base64.urlsafe_b64decode(
                data + "=="
            )

            text = decoded.decode(
                "utf-8",
                errors="ignore"
            )

            if mime_type == "text/html":

                text = re.sub(
                    r"<[^>]+>",
                    " ",
                    text
                )

            return text.strip()

        except Exception:
            pass

    parts = payload.get(
        "parts",
        []
    )

    for part in parts:

        result = extract_email_body(
            part
        )

        if result:
            return result

    return ""


# =========================================================
# GET SINGLE EMAIL
# =========================================================

@app.get("/gmail/email/{message_id}")
def get_email(
    message_id: str,
    request: Request
):

    service = get_gmail_service(
        request
    )

    if not service:

        return {
            "error": "Gmail not connected"
        }

    try:

        message = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="full"
            )
            .execute()
        )

        payload = message.get(
            "payload",
            {}
        )

        headers = payload.get(
            "headers",
            []
        )

        header_map = {}

        for header in headers:

            header_map[
                header["name"].lower()
            ] = header["value"]

        body = extract_email_body(
            payload
        )

        return {
            "id":
                message.get("id"),

            "threadId":
                message.get(
                    "threadId"
                ),

            "sender":
                header_map.get(
                    "from",
                    ""
                ),

            "from":
                header_map.get(
                    "from",
                    ""
                ),

            "to":
                header_map.get(
                    "to",
                    ""
                ),

            "subject":
                header_map.get(
                    "subject",
                    "(No subject)"
                ),

            "date":
                header_map.get(
                    "date",
                    ""
                ),

            "snippet":
                message.get(
                    "snippet",
                    ""
                ),

            "body":
                body
        }

    except Exception as e:

        print(
            "GET EMAIL ERROR:",
            repr(e)
        )

        return {
            "error": str(e)
        }


# =========================================================
# AI CHAT
# =========================================================

@app.post("/chat")
def chat(
    request_data: ChatRequest
):

    if not groq_client:

        return {
            "reply":
                "Groq API is not configured."
        }

    try:

        messages = [
            {
                "role": "system",
                "content":
                    SYSTEM_INSTRUCTION
            }
        ]

        for item in request_data.history:

            if (
                isinstance(item, dict)
                and "role" in item
                and "content" in item
            ):

                messages.append(
                    {
                        "role":
                            item["role"],

                        "content":
                            item["content"]
                    }
                )

        messages.append(
            {
                "role":
                    "user",

                "content":
                    request_data.message
            }
        )

        completion = (
            groq_client.chat.completions.create(
                model=(
                    "llama-3.3-70b-versatile"
                ),
                messages=messages,
                temperature=0.3
            )
        )

        reply = (
            completion.choices[0]
            .message.content
        )

        return {
            "reply": reply
        }

    except Exception as e:

        print(
            "CHAT ERROR:",
            repr(e)
        )

        return {
            "reply":
                "AI error occurred."
        }


# =========================================================
# EMAIL CLASSIFICATION
# =========================================================

def classify_email(
    sender,
    subject,
    body
):

    if not groq_client:

        return "Other"

    prompt = f"""
Classify this email into exactly ONE category.

Categories:

- Important
- Reply Needed
- Newsletter
- Promotion
- Notification
- Spam
- Other

Sender:
{sender}

Subject:
{subject}

Body:
{body[:5000]}

Return ONLY the category name.
"""

    try:

        completion = (
            groq_client.chat.completions.create(
                model=(
                    "llama-3.3-70b-versatile"
                ),
                messages=[
                    {
                        "role":
                            "system",

                        "content":
                            "You classify emails."
                    },
                    {
                        "role":
                            "user",

                        "content":
                            prompt
                    }
                ],
                temperature=0
            )
        )

        result = (
            completion
            .choices[0]
            .message
            .content
            .strip()
        )

        allowed = [
            "Important",
            "Reply Needed",
            "Newsletter",
            "Promotion",
            "Notification",
            "Spam",
            "Other"
        ]

        for category in allowed:

            if category.lower() == result.lower():

                return category

        return "Other"

    except Exception as e:

        print(
            "CLASSIFIER ERROR:",
            repr(e)
        )

        return "Other"


# =========================================================
# FILTERED EMAILS
# =========================================================

@app.get("/gmail/filtered-emails")
def filtered_emails(
    request: Request,
    max_results: int = 20
):

    service = get_gmail_service(
        request
    )

    if not service:

        return {
            "connected": False,
            "emails": []
        }

    try:

        result = (
            service.users()
            .messages()
            .list(
                userId="me",
                labelIds=["INBOX"],
                maxResults=max_results
            )
            .execute()
        )

        messages = result.get(
            "messages",
            []
        )

        emails = []

        for message in messages:

            try:

                full_message = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=message["id"],
                        format="full"
                    )
                    .execute()
                )

                payload = full_message.get(
                    "payload",
                    {}
                )

                headers = payload.get(
                    "headers",
                    []
                )

                header_map = {}

                for header in headers:

                    header_map[
                        header["name"].lower()
                    ] = header["value"]

                sender = header_map.get(
                    "from",
                    ""
                )

                subject = header_map.get(
                    "subject",
                    "(No subject)"
                )

                body = extract_email_body(
                    payload
                )

                classification = (
                    classify_email(
                        sender,
                        subject,
                        body
                    )
                )

                emails.append(
                    {
                        "id":
                            full_message.get(
                                "id"
                            ),

                        "sender":
                            sender,

                        "from":
                            sender,

                        "subject":
                            subject,

                        "snippet":
                            full_message.get(
                                "snippet",
                                ""
                            ),

                        "classification":
                            classification,

                        "action":
                            classification
                    }
                )

            except Exception as e:

                print(
                    "FILTER EMAIL ERROR:",
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
            "error": str(e)
        }


# =========================================================
# GENERATE DRAFT
# =========================================================

@app.get("/gmail/draft/{message_id}")
def generate_draft(
    message_id: str,
    request: Request
):

    service = get_gmail_service(
        request
    )

    if not service:

        return {
            "error":
                "Gmail not connected"
        }

    if not groq_client:

        return {
            "error":
                "Groq API is not configured."
        }

    try:

        message = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="full"
            )
            .execute()
        )

        payload = message.get(
            "payload",
            {}
        )

        headers = payload.get(
            "headers",
            []
        )

        header_map = {}

        for header in headers:

            header_map[
                header["name"].lower()
            ] = header["value"]

        sender = header_map.get(
            "from",
            ""
        )

        subject = header_map.get(
            "subject",
            ""
        )

        body = extract_email_body(
            payload
        )

        prompt = f"""
Write a professional and natural email reply.

Original sender:
{sender}

Original subject:
{subject}

Original email:
{body[:10000]}

Rules:
- Do not invent information.
- Answer the sender naturally.
- Keep it reasonably concise.
- Do not include a subject line.
- Return only the email body.
"""

        completion = (
            groq_client.chat.completions.create(
                model=(
                    "llama-3.3-70b-versatile"
                ),
                messages=[
                    {
                        "role":
                            "system",

                        "content":
                            SYSTEM_INSTRUCTION
                    },
                    {
                        "role":
                            "user",

                        "content":
                            prompt
                    }
                ],
                temperature=0.4
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
            "id":
                message_id,

            "sender":
                sender,

            "subject":
                subject,

            "draft":
                draft
        }

    except Exception as e:

        print(
            "DRAFT ERROR:",
            repr(e)
        )

        return {
            "error": str(e)
        }


# =========================================================
# SEND EMAIL
# =========================================================

@app.post("/gmail/send/{message_id}")
def send_email(
    message_id: str,
    request: Request,
    data: dict
):

    service = get_gmail_service(
        request
    )

    if not service:

        return {
            "success": False,
            "error":
                "Gmail not connected"
        }

    try:

        original = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=[
                    "From",
                    "Subject",
                    "Message-ID"
                ]
            )
            .execute()
        )

        headers = (
            original
            .get("payload", {})
            .get("headers", [])
        )

        header_map = {}

        for header in headers:

            header_map[
                header["name"].lower()
            ] = header["value"]

        recipient = header_map.get(
            "from",
            ""
        )

        subject = header_map.get(
            "subject",
            ""
        )

        if not subject.lower().startswith(
            "re:"
        ):

            subject = (
                "Re: " + subject
            )

        body = data.get(
            "body",
            data.get(
                "draft",
                ""
            )
        )

        if not body.strip():

            return {
                "success": False,
                "error":
                    "Email body is empty."
            }

        mime_message = MIMEText(
            body,
            "plain",
            "utf-8"
        )

        mime_message["To"] = recipient
        mime_message["Subject"] = subject

        thread_id = original.get(
            "threadId"
        )

        raw_message = base64.urlsafe_b64encode(
            mime_message.as_bytes()
        ).decode(
            "utf-8"
        )

        send_body = {
            "raw":
                raw_message
        }

        if thread_id:

            send_body[
                "threadId"
            ] = thread_id

        sent = (
            service.users()
            .messages()
            .send(
                userId="me",
                body=send_body
            )
            .execute()
        )

        return {
            "success": True,
            "message_id":
                sent.get("id")
        }

    except Exception as e:

        print(
            "SEND EMAIL ERROR:",
            repr(e)
        )

        return {
            "success": False,
            "error": str(e)
        }


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/health")
def health():

    return {
        "status": "healthy"
    }
@app.get("/debug/google-config")
def debug_google_config():
    client_id = GOOGLE_CLIENT_ID or ""

    return {
        "client_id_loaded": bool(client_id),
        "client_id_length": len(client_id),
        "client_id_ending": client_id[-20:] if client_id else None,
        "secret_loaded": bool(GOOGLE_CLIENT_SECRET),
        "callback_url": GOOGLE_CALLBACK_URL
    }
