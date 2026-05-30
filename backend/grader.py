import re
import logging
from dataclasses import dataclass

from . import llm
from .generator import Task, TYPE_MULTIPLE_CHOICE, TYPE_OPEN

logger = logging.getLogger("ulp.grader")


@dataclass
class Grade:
    correct: bool
    score: float
    feedback: str
    correct_answer: str


def _normalize(s: str) -> str:
    s = s.strip().lower()
    s = s.replace(",", ".")
    s = re.sub(r"\s+", "", s)
    s = s.replace("х", "x")
    return s


def _as_number(s: str):
    s = s.strip().replace(",", ".")


    m = re.match(r"\s*(-?\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\b", s)
    if m:
        try:
            den = float(m.group(2))
            return float(m.group(1)) / den if den else None
        except (ValueError, ZeroDivisionError):
            return None

    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None

    return None


def _fast_check(task: Task, user_answer: str):
    ua = user_answer.strip()
    if not ua:
        return Grade(False, 0.0, "Ответ пустой.", task.answer)


    if task.type == TYPE_MULTIPLE_CHOICE:
        if _normalize(ua) == _normalize(task.answer):
            return Grade(True, 1.0, "Верно!", task.answer)

        for c in task.choices:
            if _normalize(ua) == _normalize(c):
                ok = _normalize(c) == _normalize(task.answer)
                return Grade(ok, 1.0 if ok else 0.0,
                             "Верно!" if ok else "Неверно.", task.answer)
        return None


    if _normalize(ua) == _normalize(task.answer):
        return Grade(True, 1.0, "Верно!", task.answer)


    un, an = _as_number(ua), _as_number(task.answer)
    if un is not None and an is not None:
        tol = max(1e-6, abs(an) * 1e-3)
        if abs(un - an) <= tol:
            return Grade(True, 1.0, "Верно!", task.answer)


        return None

    return None


_JUDGE_SYSTEM = (
    "Ты — справедливый и точный проверяющий ответов школьника. "
    "Сравниваешь ответ ученика с эталоном по СМЫСЛУ, а не по символам. "
    "Эквивалентные формы записи (x = 5 и 5; 1/2 и 0.5; разные единицы; "
    "перестановка слагаемых) считаются верными. Возвращаешь только JSON."
)


def _build_judge_prompt(task: Task, user_answer: str) -> str:
    open_note = ""
    if task.type == TYPE_OPEN:
        open_note = (
            "Это развёрнутый ответ: оцени долю правильности от 0 до 1 "
            "по полноте и корректности относительно эталона."
        )
    return f"""
Предмет: {task.subject}, класс: {task.grade}.

Вопрос:
{task.question}

Эталонный правильный ответ:
{task.answer}

Ответ ученика:
{user_answer}

{open_note}

Верни JSON:
{{
  "correct": true | false,     // верен ли ответ по смыслу (для открытых: score>=0.6)
  "score": 0.0,                // доля правильности от 0 до 1
  "feedback": "одно короткое предложение для ученика на русском"
}}
""".strip()


_NEGATIVE_MARKERS = (
    "не ", "неправ", "неверн", "ошиб", "не соответств", "не совпад",
    "incorrect", "wrong", "не верно", "нет,",
)


def _consistent_feedback(correct: bool, score: float, raw: str, answer: str) -> str:
    looks_negative = any(m in raw.lower() for m in _NEGATIVE_MARKERS)
    if correct:
        if raw and not looks_negative:
            return raw
        if 0 < score < 1:
            return "Почти верно, ответ засчитан."
        return "Верно!"
    if raw and looks_negative:
        return raw
    return f"Неверно. Правильный ответ: {answer}"


def grade_answer(task: Task, user_answer: str) -> Grade:

    fast = _fast_check(task, user_answer)
    if fast is not None:
        return fast


    try:
        raw = llm.chat(
            [
                {"role": "system", "content": _JUDGE_SYSTEM},
                {"role": "user", "content": _build_judge_prompt(task, user_answer)},
            ],
            model=llm.JUDGE_MODEL,
            temperature=0.0,
            max_tokens=300,
            response_json=True,
        )
        data = llm.extract_json(raw)
        score = float(data.get("score", 0.0))
        score = max(0.0, min(1.0, score))
        correct = bool(data.get("correct")) or score >= 0.6
        raw_fb = str(data.get("feedback", "")).strip()
        feedback = _consistent_feedback(correct, score, raw_fb, task.answer)
        return Grade(correct, score, feedback, task.answer)
    except llm.LLMError as exc:
        logger.warning("Судья недоступен, fallback на строгое сравнение: %s", exc)
        ok = _normalize(user_answer) == _normalize(task.answer)
        return Grade(
            ok,
            1.0 if ok else 0.0,
            "Верно!" if ok else "Ответ не совпал с эталоном.",
            task.answer,
        )
