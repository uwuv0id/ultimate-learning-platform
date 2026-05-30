import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

from . import llm

logger = logging.getLogger("ulp.generator")


TYPE_MULTIPLE_CHOICE = "multiple_choice"
TYPE_SHORT = "short_answer"
TYPE_OPEN = "open_ended"

VALID_TYPES = {TYPE_MULTIPLE_CHOICE, TYPE_SHORT, TYPE_OPEN}


@dataclass
class Task:
    subject: str
    grade: int
    topic: str
    difficulty: str
    type: str
    question: str
    answer: str
    explanation: str
    hint: str = ""
    choices: list[str] = field(default_factory=list)
    answer_format: str = ""

    def public(self) -> dict:
        d = asdict(self)
        return d


def _difficulty_for(grade: int) -> str:
    if grade <= 4:
        return "начальная школа: простые, наглядные задания с небольшими числами"
    if grade <= 6:
        return "средняя школа: задания средней сложности по программе класса"
    if grade <= 9:
        return "старшие классы основной школы: задания уровня ОГЭ"
    return "старшая школа: задания уровня ЕГЭ, требующие нескольких шагов"


_SUBJECT_GUIDE = {
    "Алгебра": (
        "Используй уравнения, функции, системы, преобразования выражений. "
        "Формулы записывай в LaTeX внутри $...$. Избегай тривиальных примеров."
    ),
    "Геометрия": (
        "Используй фигуры, теоремы, вычисление углов, длин, площадей и объёмов. "
        "Формулы — в LaTeX внутри $...$."
    ),
    "Математика": (
        "Опирайся на программу класса. Где уместно, используй текстовые задачи. "
        "Формулы — в LaTeX внутри $...$."
    ),
    "Физика": (
        "Используй физические законы и реальные величины. В ответе обязательно "
        "единицы измерения. Формулы — в LaTeX внутри $...$."
    ),
    "Химия": (
        "Используй реакции и формулы веществ. Химические формулы пиши обычным "
        "текстом (H2SO4, NaCl), индексы — цифрами."
    ),
    "Информатика": (
        "Используй Python по программе класса. Если задача на чтение кода — "
        "помести код в поле question. Ответ — короткий результат или значение."
    ),
    "Русский язык": (
        "Задания на орфографию, пунктуацию, морфологию по программе класса. "
        "Краткий точный ответ (вставить букву, выбрать вариант, найти ошибку)."
    ),
}


def _type_hint(subject: str, grade: int) -> str:
    if subject in ("История", "Биология", "География", "Окружающий мир"):
        return TYPE_MULTIPLE_CHOICE
    if subject == "Русский язык":
        return TYPE_SHORT
    return TYPE_SHORT


_GEN_SYSTEM = (
    "Ты — опытный методист и учитель российской школы. "
    "Ты составляешь корректные задания строго по программе указанного класса "
    "и возвращаешь только валидный JSON без какого-либо текста вокруг."
)


def _build_gen_prompt(subject: str, grade: int, topic: str, prefer_type: str) -> str:
    difficulty = _difficulty_for(grade)
    guide = _SUBJECT_GUIDE.get(subject, "Составь задание строго по программе класса.")
    topic_text = topic.strip() or "любая тема в рамках программы класса"

    return f"""
Составь ОДНО учебное задание.

Предмет: {subject}
Класс: {grade}
Тема: {topic_text}
Уровень сложности: {difficulty}

Указания по предмету:
{guide}

Предпочтительный тип задания: {prefer_type}
Допустимые типы:
- "multiple_choice": вопрос с 4 вариантами ответа (ровно один верный).
- "short_answer": вопрос с коротким однозначным ответом (число, слово, формула).
- "open_ended": вопрос, требующий развёрнутого ответа (используй редко).

Требования:
- Задание корректное и решаемое, ответ — однозначный и проверяемый.
- "answer" — это правильный ответ в каноничной краткой форме.
  Для multiple_choice "answer" должен ТОЧНО совпадать с одним из "choices".
- "explanation" — краткий разбор (1–3 предложения), как получить ответ.
- "hint" — подсказка, которая направляет, но НЕ раскрывает ответ.
- Формулы по математике/физике записывай в LaTeX внутри $...$.

Верни СТРОГО такой JSON:
{{
  "type": "short_answer | multiple_choice | open_ended",
  "question": "текст задания",
  "choices": ["..."],            // только для multiple_choice, иначе []
  "answer": "правильный ответ",
  "explanation": "краткий разбор",
  "hint": "подсказка, не раскрывающая ответ"
}}
""".strip()


_VERIFY_SYSTEM = (
    "Ты — строгий проверяющий. Тебе дают задание и предложенный ответ. "
    "Реши задание самостоятельно и сравни. Возвращай только валидный JSON."
)


def _build_verify_prompt(task: Task) -> str:
    return f"""
Проверь корректность задания и его ответа.

Предмет: {task.subject}, класс: {task.grade}.
Вопрос:
{task.question}

Варианты (если есть): {task.choices}
Предложенный правильный ответ: {task.answer}

Реши задание сам. Затем верни JSON:
{{
  "is_correct": true | false,        // верен ли предложенный ответ
  "correct_answer": "твой ответ",    // правильный ответ по твоему решению
  "issue": "что не так, если is_correct=false, иначе пустая строка"
}}
""".strip()


def _answer_format_hint(subject: str) -> str:
    hints = {
        "Алгебра": "Введите итоговый ответ, например: x = 5  или  2; 3",
        "Геометрия": "Введите число с единицами, например: 12 см",
        "Математика": "Введите краткий ответ, например: 42  или  3/4",
        "Физика": "Введите число и единицу измерения, например: 12 м/с",
        "Химия": "Запишите формулу аккуратно, например: H2SO4",
        "Информатика": "Введите результат или короткий код.",
    }
    return hints.get(subject, "Введите краткий и точный ответ.")


def _parse_task(raw: dict, subject: str, grade: int, topic: str) -> Task:
    t = str(raw.get("type", "")).strip()
    if t not in VALID_TYPES:
        t = TYPE_SHORT

    question = str(raw.get("question", "")).strip()
    answer = str(raw.get("answer", "")).strip()
    explanation = str(raw.get("explanation", "")).strip()
    hint = str(raw.get("hint", "")).strip()

    choices = raw.get("choices") or []
    if not isinstance(choices, list):
        choices = []
    choices = [str(c).strip() for c in choices if str(c).strip()]

    if t == TYPE_MULTIPLE_CHOICE:

        if answer and answer not in choices:
            choices = (choices + [answer])[:4] if len(choices) < 4 else choices
            if answer not in choices:
                choices[-1] = answer
        if len(choices) < 2:

            t = TYPE_SHORT
            choices = []

    if not question or not answer:
        raise llm.LLMError("Модель вернула неполное задание")

    return Task(
        subject=subject,
        grade=grade,
        topic=topic,
        difficulty=_difficulty_for(grade),
        type=t,
        question=question,
        answer=answer,
        explanation=explanation,
        hint=hint,
        choices=choices,
        answer_format=_answer_format_hint(subject),
    )


def _verify(task: Task) -> tuple[bool, str]:
    if task.type == TYPE_OPEN:
        return True, task.answer
    if not llm.SELF_VERIFY:
        return True, task.answer
    try:
        raw = llm.chat(
            [
                {"role": "system", "content": _VERIFY_SYSTEM},
                {"role": "user", "content": _build_verify_prompt(task)},
            ],
            model=llm.JUDGE_MODEL,
            temperature=0.0,
            max_tokens=400,
            response_json=True,
        )
        data = llm.extract_json(raw)
        ok = bool(data.get("is_correct"))
        corrected = str(data.get("correct_answer", "")).strip()
        if not ok and corrected:
            return False, corrected
        return ok, task.answer
    except llm.LLMError as exc:

        logger.warning("Самопроверка пропущена: %s", exc)
        return True, task.answer


def generate_task(
    subject: str,
    grade: int,
    topic: str = "",
    max_attempts: int = 3,
) -> Task:
    prefer = _type_hint(subject, grade)
    prompt = _build_gen_prompt(subject, grade, topic, prefer)

    last_task: Optional[Task] = None

    for attempt in range(1, max_attempts + 1):
        raw = llm.chat(
            [
                {"role": "system", "content": _GEN_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            model=llm.GEN_MODEL,
            temperature=0.6 if attempt == 1 else 0.8,
            max_tokens=2000,
            timeout=120,
            response_json=True,
        )
        data = llm.extract_json(raw)
        task = _parse_task(data, subject, grade, topic)
        last_task = task

        ok, corrected = _verify(task)
        if ok:
            return task


        if corrected and corrected != task.answer:
            logger.info("Ответ исправлен самопроверкой: %r -> %r", task.answer, corrected)
            task.answer = corrected
            return task

        logger.info("Задание не прошло самопроверку, попытка %s", attempt)


    if last_task is None:
        raise llm.LLMError("Не удалось сгенерировать задание")
    return last_task
