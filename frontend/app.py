import re
import requests
import streamlit as st

API = "http://127.0.0.1:8000"

st.set_page_config(
    page_title="Персонализированное обучение",
    page_icon="🎓",
    layout="wide",
)


for key, default in {
    "token": None,
    "user": None,
    "saved_grade": 5,
    "xp": 0,
    "level": 1,
    "streak": 0,
    "task": None,
    "checked": None,
    "show_hint": False,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


st.markdown("""
<style>
.stApp { background: linear-gradient(135deg,#0f172a,#111827); color:#e5e7eb; }
section[data-testid="stSidebar"] { background:#111827; border-right:1px solid #374151; }
h1,h2,h3,h4,h5,h6,p,label,span { color:#e5e7eb !important; }
.stButton > button {
  width:100%; border-radius:14px; height:3.1em; font-size:16px; border:none;
  background:linear-gradient(90deg,#2563eb,#1d4ed8); color:#fff; font-weight:bold;
  transition:.15s;
}
.stButton > button:hover { transform:scale(1.01); filter:brightness(1.07); }
.stTextInput input { background:#1f2937; color:#fff; border-radius:10px; }
textarea { background:#1f2937 !important; color:#fff !important; }
div[data-baseweb="select"] > div { background:#1f2937 !important; color:#fff !important; }
.task-card {
  background:#0b1220; padding:24px; border-radius:18px; border:1px solid #374151;
  margin:14px 0 18px; line-height:1.7; font-size:19px; white-space:pre-wrap;
}
.answer-box { background:#0f172a; padding:16px; border-radius:14px;
  border:1px solid #334155; margin-top:10px; }
.badge { display:inline-block; padding:6px 12px; border-radius:999px;
  background:#1e293b; border:1px solid #334155; margin-right:8px; font-size:14px; }
/* Карточка задания: bordered-контейнер Streamlit */
div[data-testid="stVerticalBlockBorderWrapper"] {
  background:#0b1220; border:1px solid #374151 !important;
  border-radius:18px; padding:8px 22px; margin:14px 0 18px;
}
div[data-testid="stVerticalBlockBorderWrapper"] p {
  font-size:19px !important; line-height:1.75 !important; margin:6px 0;
}
/* Inline-формулы KaTeX не должны раздуваться */
div[data-testid="stVerticalBlockBorderWrapper"] .katex { font-size:1.05em; }
</style>
""", unsafe_allow_html=True)


def _headers():
    if st.session_state.token:
        return {"Authorization": f"Bearer {st.session_state.token}"}
    return {}


def api_get(path):
    return requests.get(f"{API}{path}", headers=_headers(), timeout=30)


def api_post(path, json=None):
    return requests.post(f"{API}{path}", json=json, headers=_headers(), timeout=150)


def _err_detail(resp):
    try:
        return resp.json().get("detail", resp.text)
    except Exception:
        return resp.text


try:
    catalog = api_get("/catalog").json()
except Exception:
    st.error("❌ Backend не запущен. Запустите: python start.py")
    st.stop()


def _tidy_question(text: str) -> str:
    if not text:
        return ""

    text = re.sub(r"\$\$\s*(.+?)\s*\$\$", r"$\1$", text, flags=re.DOTALL)


    text = re.sub(r"[ \t]*\n[ \t]*\n[ \t]*", "\n\n", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)

    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def render_question(subject, question):
    question = _tidy_question(question)


    if subject.lower() == "информатика" and ("def " in question or "print(" in question):
        st.code(question, language="python")
        return


    with st.container(border=True):

        st.markdown(question)


if not st.session_state.token:
    st.title("🎓 Персонализированное обучение")
    st.markdown("""
Интеллектуальная платформа, которая:
- генерирует задания по школьной программе РФ под нужный класс и тему,
- проверяет ответы **по смыслу** (понимает разные формы записи),
- ведёт прогресс, уровни и серии правильных ответов.
""")

    mode = st.radio("Авторизация", ["Вход", "Регистрация"], horizontal=True)
    username = st.text_input("Логин")
    password = st.text_input("Пароль", type="password")
    if mode == "Регистрация":
        st.info("Пароль: минимум 8 символов, заглавная и строчная буквы, цифра.")

    if st.button("Продолжить"):
        if not username or not password:
            st.warning("Введите логин и пароль")
            st.stop()
        endpoint = "/register" if mode == "Регистрация" else "/login"
        try:
            resp = api_post(endpoint, json={"username": username, "password": password})
        except Exception as e:
            st.error("Ошибка подключения")
            st.code(str(e))
            st.stop()

        if resp.status_code != 200:
            st.error(_err_detail(resp))
        else:
            data = resp.json()
            st.session_state.token = data["token"]
            st.session_state.user = data["username"]
            st.session_state.saved_grade = data.get("saved_grade", 5)
            st.session_state.xp = data.get("xp", 0)
            st.session_state.level = data.get("level", 1)
            st.session_state.streak = data.get("streak", 0)
            st.rerun()
    st.stop()


st.sidebar.title("⚙️ Параметры")
st.sidebar.success(f"👤 {st.session_state.user}")


st.sidebar.markdown(
    f"""<div>
    <span class="badge">⭐ Уровень {st.session_state.level}</span>
    <span class="badge">✨ {st.session_state.xp} XP</span>
    <span class="badge">🔥 Серия {st.session_state.streak}</span>
    </div>""",
    unsafe_allow_html=True,
)

grade = st.sidebar.selectbox(
    "Класс", list(range(1, 12)),
    index=max(0, min(10, st.session_state.saved_grade - 1)),
)
if st.sidebar.button("💾 Сохранить класс"):
    try:
        r = api_post("/save-grade", json={"grade": grade})
        if r.status_code == 200:
            st.session_state.saved_grade = grade
            st.sidebar.success("Сохранено")
        else:
            st.sidebar.error(_err_detail(r))
    except Exception:
        st.sidebar.error("Ошибка сохранения")

with st.sidebar.expander("📊 Моя статистика"):
    try:
        s = api_get("/stats").json()
        st.write(f"Всего: **{s['total']}**, верно: **{s['correct']}** "
                 f"(точность {int(s['accuracy']*100)}%)")
        for row in s.get("by_subject", []):
            tot, cor = row["total"], row["correct"] or 0
            st.write(f"• {row['subject']}: {cor}/{tot}")
    except Exception:
        st.caption("Пока нет данных")

if st.sidebar.button("🚪 Выйти"):
    try:
        api_post("/logout")
    except Exception:
        pass
    for k in ("token", "user", "task", "checked"):
        st.session_state[k] = None
    st.rerun()


st.title(f"📚 {grade} класс")

subjects = catalog["grades"].get(str(grade), [])
subject = st.selectbox("Предмет", subjects)

gen_mode = st.radio("Режим", ["Весь предмет", "По темам"], horizontal=True)
topic = ""
if gen_mode == "По темам":
    subj_topics = catalog["topics"].get(subject, {})
    topics = subj_topics.get(str(grade), []) if isinstance(subj_topics, dict) else subj_topics
    topic = st.selectbox("Тема", topics or ["Общая тема"])

c1, c2 = st.columns([3, 1])
with c1:
    gen_clicked = st.button("🧠 Сгенерировать задание")
with c2:
    clear_clicked = st.button("🗑 Очистить")

if clear_clicked:
    st.session_state.task = None
    st.session_state.checked = None
    st.session_state.show_hint = False
    st.rerun()

if gen_clicked:
    with st.spinner("Генерация и самопроверка задания..."):
        try:
            r = api_post("/generate", json={
                "grade": grade, "subject": subject, "topic": topic})
        except Exception as e:
            st.error("Ошибка backend")
            st.code(str(e))
            st.stop()
    if r.status_code != 200:
        st.error(_err_detail(r))
        st.stop()
    st.session_state.task = r.json()
    st.session_state.checked = None
    st.session_state.show_hint = False


task = st.session_state.task
if task:
    st.subheader("📘 Задание")
    render_question(subject, task.get("question", ""))

    st.caption(f"📊 {task.get('difficulty','')}")

    if task.get("hint"):
        if st.button("💡 Подсказка"):
            st.session_state.show_hint = True
        if st.session_state.show_hint:
            st.info(f"💡 {task['hint']}")

    st.markdown("### 📝 Ваш ответ")
    ttype = task.get("type", "short_answer")

    if ttype == "multiple_choice" and task.get("choices"):
        user_answer = st.radio("Выберите вариант:", task["choices"], index=None)
    elif ttype == "open_ended":
        user_answer = st.text_area("Развёрнутый ответ", height=180)
    elif subject.lower() == "информатика":
        user_answer = st.text_area("Ваш ответ / код", height=160)
    else:
        st.caption(task.get("answer_format", ""))
        user_answer = st.text_input("Введите ответ")

    if st.button("✅ Проверить ответ"):
        if not user_answer or not str(user_answer).strip():
            st.warning("Введите ответ")
        else:
            with st.spinner("Проверяем ответ..."):
                try:
                    r = api_post("/check", json={
                        "task": task, "user_answer": str(user_answer)})
                except Exception as e:
                    st.error("Ошибка проверки")
                    st.code(str(e))
                    st.stop()
            if r.status_code != 200:
                st.error(_err_detail(r))
                st.stop()
            st.session_state.checked = r.json()

            prog = st.session_state.checked.get("progress", {})
            st.session_state.xp = prog.get("xp", st.session_state.xp)
            st.session_state.level = prog.get("level", st.session_state.level)
            st.session_state.streak = prog.get("streak", st.session_state.streak)


    res = st.session_state.checked
    if res:
        st.divider()
        if res["correct"]:
            gained = res.get("progress", {}).get("xp_gained", 0)
            st.success(f"✅ {res.get('feedback','Верно!')}  (+{gained} XP)")
        else:
            st.error(f"❌ {res.get('feedback','Неверно.')}")
            st.markdown("**Правильный ответ:**")
            with st.container(border=True):
                st.markdown(_tidy_question(res.get("correct_answer", "")))
        if res.get("score") is not None and 0 < res["score"] < 1:
            st.caption(f"Оценка: {int(res['score']*100)}%")
        if res.get("explanation"):
            st.markdown("### 📖 Объяснение")
            with st.container(border=True):
                st.markdown(_tidy_question(res["explanation"]))
