from biomeagent.direction import message_view, readable_formula, text_direction


def test_the_first_letter_decides_the_message():
    assert text_direction("فارسی بگو") == "rtl"
    assert text_direction("# گونه‌های کلیدی") == "rtl"
    assert text_direction("1. عنوان") == "rtl"
    assert text_direction("Hello") == "ltr"
    assert text_direction("IBS و میکروب") == "ltr"
    assert text_direction("   ") == "ltr"


def test_latex_formula_is_plain_text_with_the_charge_at_the_end():
    latex = r"`$-\text{C}_4\text{H}_7\text{O}_2$`"
    assert readable_formula(r"-\text{C}_4\text{H}_7\text{O}_2") == "C4H7O2-"
    kind, body = message_view(f"فرمول {latex} است")
    assert kind == "html"
    assert "C4H7O2-" in body
    assert "text" not in body
    assert r"\text" not in body
    english_kind, english = message_view(f"Formula {latex}.")
    assert english_kind == "markdown"
    assert "`C4H7O2-`" in english


def test_a_plain_formula_stays_one_left_to_right_run():
    kind, body = message_view("فرمول C4H7O2- است")
    assert kind == "html"
    assert "<code>C4H7O2-</code>" in body


def test_rtl_message_is_rendered_html_and_english_stays_markdown():
    kind, body = message_view("فارسی **بگو**")
    assert kind == "html"
    assert body.startswith('<div dir="rtl">')
    assert "<strong>بگو</strong>" in body
    assert message_view("Hello **there**") == ("markdown", "Hello **there**")
