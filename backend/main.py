import json
import logging
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from . import db, generator, grader, llm

_BACKEND_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _BACKEND_DIR.parent
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv(_ROOT_DIR / ".env")
load_dotenv()
logging.basicConfig(level=logging.INFO)

BASE_DIR = Path(__file__).resolve().parent
CATALOG = json.loads((BASE_DIR / "curriculum.json").read_text(encoding="utf-8"))

db.init_db()

app = FastAPI(title="Ultimate Learning Platform", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Auth(BaseModel):
    username: str
    password: str


class SaveGrade(BaseModel):
    grade: int


class GenerateReq(BaseModel):
    grade: int
    subject: str
    topic: str = ""


class CheckReq(BaseModel):

    task: dict
    user_answer: str


def _require_user(authorization: str | None) -> str:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    user = db.session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Требуется вход")
    return user


@app.get("/")
def home():
    return {"status": "ok", "version": "2.0"}


@app.get("/catalog")
def catalog():
    return CATALOG


@app.post("/register")
def register(data: Auth):
    err = db.validate_password(data.password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    try:
        user = db.create_user(data.username, data.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    token = db.create_session(user["username"])
    return {"token": token, **user}


@app.post("/login")
def login(data: Auth):
    if not db.verify_user(data.username, data.password):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    user = db.get_user(data.username)
    token = db.create_session(data.username)
    return {"token": token, **user}


@app.post("/logout")
def logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.lower().startswith("bearer "):
        db.delete_session(authorization[7:].strip())
    return {"status": "ok"}


@app.post("/save-grade")
def save_grade(data: SaveGrade, authorization: str | None = Header(default=None)):
    user = _require_user(authorization)
    db.save_grade(user, data.grade)
    return {"status": "saved", "saved_grade": data.grade}


@app.post("/generate")
def generate(data: GenerateReq, authorization: str | None = Header(default=None)):
    _require_user(authorization)
    try:
        task = generator.generate_task(data.subject, data.grade, data.topic)
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return task.public()


@app.post("/check")
def check(data: CheckReq, authorization: str | None = Header(default=None)):
    user = _require_user(authorization)


    t = data.task
    try:
        task = generator.Task(
            subject=str(t.get("subject", "")),
            grade=int(t.get("grade", 0)),
            topic=str(t.get("topic", "")),
            difficulty=str(t.get("difficulty", "")),
            type=str(t.get("type", generator.TYPE_SHORT)),
            question=str(t.get("question", "")),
            answer=str(t.get("answer", "")),
            explanation=str(t.get("explanation", "")),
            hint=str(t.get("hint", "")),
            choices=list(t.get("choices", []) or []),
            answer_format=str(t.get("answer_format", "")),
        )
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Некорректное задание")

    result = grader.grade_answer(task, data.user_answer)

    progress = db.record_attempt(
        username=user,
        subject=task.subject,
        topic=task.topic,
        question=task.question,
        user_answer=data.user_answer,
        correct_answer=result.correct_answer,
        is_correct=result.correct,
        score=result.score,
    )

    return {
        "correct": result.correct,
        "score": result.score,
        "feedback": result.feedback,
        "correct_answer": result.correct_answer,
        "explanation": task.explanation,
        "progress": progress,
    }


@app.get("/stats")
def stats(authorization: str | None = Header(default=None)):
    user = _require_user(authorization)
    return db.stats(user)
