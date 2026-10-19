import pytest

from ruralminds import tutor
from ruralminds.answer import AskRequest, Gate, _save_unanswered
from ruralminds.db import connect, init_schema
from ruralminds.notes import ChunkText, group_chunks, parse_points
from ruralminds.uploads import trim_logs


@pytest.mark.parametrize(
    ("question", "mode"),
    [
        ("explain why harappan civilization failed using a real world example", "example"),
        ("explain as a story ignore the text because i didnt understand yet", "story"),
        ("can you summarize the entire chapter 2 for me to learn fast", "summary"),
        ("I didn't understand, explain in simple words", "simpler"),
        ("quiz me on Bhimbetka", "quiz"),
        ("manassilayilla, onnu koode parayamo", "simpler"),
        ("ഹരപ്പയെക്കുറിച്ച് ഒരു കഥ പറയൂ", "story"),
        ("Where is Bhimbetka?", "explain"),
    ],
)
def test_detect_mode(question: str, mode: str) -> None:
    assert tutor.detect_mode(question) == mode


def test_topic_query_drops_request_words() -> None:
    query = tutor.topic_query("explain why harappan civilization failed using a real world example")
    assert query == "why harappan civilization failed"
    assert tutor.chapter_in("summarize the entire chapter 2 please") == 2
    assert tutor.chapter_in("അധ്യായം 4 ചുരുക്കി പറയൂ") == 4


@pytest.mark.parametrize(
    ("question", "language"),
    [
        ("river valleys enthanu?", "manglish"),
        ("Bhimbetka evideyanu", "manglish"),
        ("harappan nagarangalile drainage engane aayirunnu", "manglish"),
        ("Where is Bhimbetka?", "en"),
        ("What are the parts of the civil service until 1950?", "en"),
        ("ഭിംബേഡ്ക എവിടെയാണ്?", "ml"),
    ],
)
def test_question_language(question: str, language: str) -> None:
    assert tutor.question_language(question) == language


def test_answer_language_follows_setting_then_question() -> None:
    assert tutor.answer_language("en", "ഭിംബേഡ്ക എവിടെയാണ്?") == "en"
    assert tutor.answer_language("auto", "river valleys enthanu?") == "ml"
    assert tutor.answer_language("auto", "Where is Bhimbetka?") == "en"


def test_split_sections_any_order_and_malayalam_labels() -> None:
    text = (
        "Harappa had **drains** [S1].\n- covered [S1]\n"
        "EXAMPLE: like town drains [S2]\nCHECK: Why cover drains?"
    )
    parts = tutor.split_sections(text)
    assert parts.explanation == "Harappa had **drains** [S1].\n- covered [S1]"
    assert parts.example == "like town drains [S2]"  # markers are stripped later, in answer.py
    assert parts.check == "Why cover drains?"
    malayalam = tutor.split_sections(
        "ഓടകൾ [S1]\n**ഉദാഹരണം:** വീട്ടിലെ പൈപ്പ്\nസ്വയം പരിശോധിക്കാം: എന്തുകൊണ്ട്?"
    )
    assert malayalam.example == "വീട്ടിലെ പൈപ്പ്" and malayalam.check == "എന്തുകൊണ്ട്?"
    quiz = tutor.split_sections("1. Where? [S1]\nANSWERS: 1. Madhya Pradesh [S1]")
    assert quiz.answers == "1. Madhya Pradesh [S1]"


def test_notes_points_keep_only_cited_bullets_with_our_pages() -> None:
    group = [ChunkText("a", 11, 12, 200), ChunkText("b", 13, 13, 200)]
    reply = "- Bhimbetka is in Madhya Pradesh [S1]\n- Something uncited\n- Tools changed [S2] [S9]\nNotes"
    points = parse_points(reply, group)
    assert [p["text"] for p in points] == ["Bhimbetka is in Madhya Pradesh", "Tools changed"]
    assert (points[0]["page_start"], points[0]["page_end"]) == (11, 12)
    assert (points[1]["page_start"], points[1]["page_end"]) == (13, 13)


def test_group_chunks_respects_budget() -> None:
    chunks = [ChunkText("x", 1, 1, 400) for _ in range(5)]
    assert [len(group) for group in group_chunks(chunks, budget=900)] == [2, 2, 1]


@pytest.fixture
def conn():
    connection = connect(":memory:")
    init_schema(connection)
    yield connection
    connection.close()


def _refusal(conn, question: str, class_id: int = 1) -> None:
    request = AskRequest(question, "en", "en", class_id=class_id, document_id=1)
    gate = Gate(top_similarity=0.3, keyword_hit=False, top_rrf=None, candidates=0, passed=False)
    _save_unanswered(conn, request, gate)


def test_inbox_groups_repeats(conn) -> None:
    for question in ("Who won the World Cup?", "who won the world cup", "WHO WON THE WORLD CUP?!"):
        _refusal(conn, question)
    rows = conn.execute("SELECT times_asked FROM unanswered").fetchall()
    assert [row[0] for row in rows] == [3]


def test_retention_bounds_the_inbox(conn, monkeypatch) -> None:
    from ruralminds.config import settings

    monkeypatch.setattr(settings, "unanswered_keep_per_class", 2)
    for number in range(4):
        _refusal(conn, f"question {number}")
    conn.execute(
        "INSERT INTO unanswered (question, class_id, document_id, normalised_q, last_asked)"
        " VALUES ('old', 2, 1, 'old', datetime('now', '-40 days'))"
    )
    with conn:
        trim_logs(conn)
    per_class = dict(
        conn.execute("SELECT class_id, count(*) FROM unanswered GROUP BY 1").fetchall()
    )
    assert per_class == {1: 2}


def test_notes_points_close_the_gap_left_by_markers() -> None:
    points = parse_points("- Bhimbetka is in Madhya Pradesh [S1].", [ChunkText("a", 11, 11, 10)])
    assert points[0]["text"] == "Bhimbetka is in Madhya Pradesh."


def test_follow_ups_keep_the_topic() -> None:
    from ruralminds.answer import Turn, _retrieval_query

    history = [
        Turn("why did the harappan civilization fail", "Floods [S1]."),
        Turn("explain as a story ignore the text because i didnt understand yet", "Once [S1]."),
    ]
    chip = AskRequest("Give me a real-life example.", "en", "en", history=history)
    assert _retrieval_query(chip) == "why did the harappan civilization fail"
    typed = AskRequest("Where is Bhimbetka?", "en", "en")
    assert _retrieval_query(typed) == "Where is Bhimbetka?"


def test_answers_that_admit_the_book_lacks_it_are_caught() -> None:
    assert tutor.admits_missing("- The sources do not specifically state the boiling point.")
    assert tutor.admits_missing("The text does not provide a real-world example.")
    assert tutor.admits_missing("ഇത് പുസ്തകത്തിൽ പറയുന്നില്ല.")
    assert not tutor.admits_missing("Harappan drains were covered with stone slabs [S1].")


def test_answers_in_the_wrong_script_are_caught() -> None:
    hindi = "भारत में पहले राष्ट्रपति कौन थे, यह जानकारी दी गई है और वे मुखिया होते हैं"
    assert tutor.wrong_script(hindi, "ml") and tutor.wrong_script(hindi, "en")
    assert not tutor.wrong_script("ഹരപ്പൻ നഗരങ്ങളിൽ മൂടിയ ഓടകൾ ഉണ്ടായിരുന്നു (Harappa)", "ml")
    assert not tutor.wrong_script("Harappan cities had covered drains to carry water.", "en")


@pytest.mark.parametrize(
    "question",
    [
        "Who is the Chief Minister of Kerala now?",
        "Who is the present President of India?",
        "Name the current Prime Minister",
        "kerala ippozhathe mukhyamanthri aaranu?",
        "കേരളത്തിന്റെ ഇപ്പോഴത്തെ മുഖ്യമന്ത്രി ആരാണ്?",
    ],
)
def test_who_holds_an_office_now_is_time_sensitive(question: str) -> None:
    assert tutor.time_sensitive(question)


@pytest.mark.parametrize(
    "question",
    [
        "What are the powers of the President?",  # no "now": the book answers this
        "Who elects the Chief Minister?",  # no "now"
        "Who were the rulers present at the Kalinga war?",  # "present", but no office
        "How is the Prime Minister chosen now?",  # how, not who
        "രാഷ്ട്രപതിയുടെ അധികാരങ്ങൾ എന്തൊക്കെ?",
    ],
)
def test_book_questions_about_offices_are_not_time_sensitive(question: str) -> None:
    assert not tutor.time_sensitive(question)


def test_third_script_catches_one_stray_word_only() -> None:
    assert tutor.third_script("രാജ്യസഭയും ലോകസഭയും ഈ പാർലമെന്റിനെ 구성 ചെയ്യുന്നു")
    assert tutor.third_script("ഇത് కలగ ആണ്")  # Telugu
    assert not tutor.third_script("ഹാരപ്പ (Harappa) BCE 2600 – café")


def test_notes_wait_while_a_student_answer_is_generating() -> None:
    import asyncio

    import httpx

    from ruralminds.notes import wait_for_idle_model

    replies = iter(
        [[{"is_processing": True}, {"is_processing": False}], [{"is_processing": False}] * 2]
    )
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=next(replies))

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await wait_for_idle_model(client, poll_s=0)

    asyncio.run(scenario())
    assert calls == ["/slots", "/slots"]  # waited once, then went ahead


def test_notes_go_ahead_when_slots_cannot_be_read() -> None:
    import asyncio

    import httpx

    from ruralminds.notes import wait_for_idle_model

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no server")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await wait_for_idle_model(client, poll_s=0)

    asyncio.run(scenario())
