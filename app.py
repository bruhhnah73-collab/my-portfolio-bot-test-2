from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from groq import Groq
from email.mime.text import MIMEText
import os
import base64
import re

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build


app = FastAPI()


# =========================
# CORS
# =========================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# API KEYS
# =========================

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()

client = Groq(api_key=GROQ_API_KEY)


# =========================
# GMAIL SETTINGS
# =========================

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose"
]

gmail_credentials = None
agent_enabled = True


# =========================
# AI CHAT INSTRUCTIONS
# =========================

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


class ChatRequest(BaseModel):
    message: str
    conversation: list[dict] = []


class SendEmailRequest(BaseModel):
    draft: str


# =========================
# GMAIL SERVICE
# =========================

def get_gmail_service():

    if gmail_credentials is None:
        return None

    return build(
        "gmail",
        "v1",
        credentials=gmail_credentials
    )


# =========================
# GMAIL AUTH
# =========================

@app.get("/gmail/auth")
def gmail_auth(response: Response):

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

    flow.redirect_uri = (
        "https://my-portfolio-bot-test-2.onrender.com/gmail/callback"
    )

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true"
    )

    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=600
    )

    response.set_cookie(
        key="oauth_verifier",
        value=flow.code_verifier,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=600
    )

    return {
        "authorization_url": authorization_url
    }


# =========================
# GMAIL CALLBACK
# =========================

@app.get("/gmail/callback")
def gmail_callback(
    request: Request,
    code: str,
    state: str
):

    global gmail_credentials

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

    flow.redirect_uri = (
        "https://my-portfolio-bot-test-2.onrender.com/gmail/callback"
    )

    flow.code_verifier = code_verifier

    flow.fetch_token(code=code)

    gmail_credentials = flow.credentials

    redirect = RedirectResponse(
        url="https://email-agent-panel.onrender.com/"
    )

    redirect.delete_cookie("oauth_state")
    redirect.delete_cookie("oauth_verifier")

    return redirect


# =========================
# GMAIL STATUS
# =========================

@app.get("/gmail/status")
def gmail_status():

    return {
        "connected": gmail_credentials is not None
    }


# =========================
# GET INBOX EMAILS
# =========================

@app.get("/gmail/emails")
def get_emails():

    service = get_gmail_service()

    if service is None:
        return {
            "connected": False,
            "emails": []
        }

    results = service.users().messages().list(
        userId="me",
        maxResults=10,
        labelIds=["INBOX"]
    ).execute()

    messages = results.get(
        "messages",
        []
    )

    emails = []

    for message in messages:

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
            "snippet": data.get(
                "snippet",
                ""
            )
        })

    return {
        "connected": True,
        "emails": emails
    }


# =========================
# GET ONE EMAIL
# =========================

@app.get("/gmail/email/{email_id}")
def get_email(email_id: str):

    service = get_gmail_service()

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


# =========================
# HOME
# =========================

@app.get("/")
def home():

    return {
        "status": "AI agent backend is running!",
        "agent_enabled": agent_enabled
    }


# =========================
# AGENT ON
# =========================

@app.post("/agent/on")
def agent_on():

    global agent_enabled

    agent_enabled = True

    return {
        "agent_enabled": True
    }


# =========================
# AGENT OFF
# =========================

@app.post("/agent/off")
def agent_off():

    global agent_enabled

    agent_enabled = False

    return {
        "agent_enabled": False
    }


# =========================
# AGENT STATUS
# =========================

@app.get("/agent/status")
def agent_status():

    return {
        "agent_enabled": agent_enabled
    }


# =========================
# AI CHAT
# =========================

@app.post("/chat")
def chat(request: ChatRequest):

    if not agent_enabled:

        return {
            "response": None,
            "agent_enabled": False
        }

    messages = [
        {
            "role": "system",
            "content": SYSTEM_INSTRUCTION
        }
    ]

    messages.extend(request.conversation)

    messages.append({
        "role": "user",
        "content": request.message
    })

    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=messages,
        temperature=0.6,
        max_completion_tokens=1024
    )

    return {
        "response": completion.choices[0].message.content,
        "agent_enabled": True
    }


# =========================
# EMAIL CLASSIFIER
# =========================

def classify_email(sender, subject, snippet):

    sender = sender.lower()
    subject = subject.lower()
    snippet = snippet.lower()

    text = f"{sender} {subject} {snippet}"

    # AUTOMATED EMAILS

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

    # PORTFOLIO QUESTIONS

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

    if has_portfolio_topic and has_question:
        return "PROCESS"

    # AI CLASSIFIER

    completion = client.chat.completions.create(
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

If a real person appears to be contacting the creator and expects a
response, choose PROCESS.

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

    result = (
        completion.choices[0]
        .message
        .content
        .strip()
        .upper()
    )

    if result == "PROCESS":
        return "PROCESS"

    return "IGNORE"


# =========================
# FILTER ONE EMAIL
# =========================

@app.post("/gmail/filter/{email_id}")
def filter_email(email_id: str):

    service = get_gmail_service()

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
        sender,
        subject,
        snippet
    )

    return {
        "email_id": email_id,
        "classification": classification
    }


# =========================
# FILTER ALL EMAILS
# =========================

@app.get("/gmail/filtered-emails")
def filtered_emails():

    service = get_gmail_service()

    if service is None:
        return {
            "connected": False,
            "emails": []
        }

    results = service.users().messages().list(
        userId="me",
        maxResults=10,
        labelIds=["INBOX"]
    ).execute()

    messages = results.get(
        "messages",
        []
    )

    emails = []

    for message in messages:

        email_id = message["id"]

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
            sender,
            subject,
            snippet
        )

        emails.append({
            "id": email_id,
            "from": sender,
            "subject": subject,
            "snippet": snippet,
            "classification": classification
        })

    return {
        "connected": True,
        "emails": emails
    }


# =========================
# GENERATE EMAIL DRAFT
# =========================

@app.post("/gmail/draft/{email_id}")
def generate_email_draft(email_id: str):

    service = get_gmail_service()

    if service is None:
        return {
            "connected": False,
            "error": "Gmail is not connected"
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

    # GET EMAIL BODY

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

    # GENERATE AI REPLY

    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
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


# =========================
# SEND EMAIL REPLY
# =========================

@app.post("/gmail/send/{email_id}")
def send_gmail_reply(
    email_id: str,
    request: SendEmailRequest
):

    draft = request.draft

    if not gmail_credentials:
        return {
            "success": False,
            "message": "Gmail is not connected."
        }

    try:

        service = get_gmail_service()

        original = service.users().messages().get(
            userId="me",
            id=email_id,
            format="metadata",
            metadataHeaders=["From", "Subject"]
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

            if header["name"].lower() == "from":
                sender = header["value"]

            if header["name"].lower() == "subject":
                subject = header["value"]

        if not sender:
            return {
                "success": False,
                "message": "Could not find the sender."
            }

        if not draft.strip():
            return {
                "success": False,
                "message": "Draft cannot be empty."
            }

        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        # CONVERT MARKDOWN BOLD TO HTML BOLD

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
            "threadId": original.get("threadId")
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

        print("Gmail send error:", e)

        return {
            "success": False,
            "message": "Failed to send the email."
        }
