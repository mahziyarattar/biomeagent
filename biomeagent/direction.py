"""Message direction. The first letter decides the whole message."""

import re

import markdown

_CODE_SPAN = re.compile(r"(`[^`\n]*`)")
_MATH = re.compile(r"\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$")
_BARE_FORMULA = re.compile(r"(?<![\w])([A-Z][a-z]?(?:\d+[A-Z][a-z]?)+\d*[+-]?)(?![\w])")

_RTL_START = (
    (0x0590, 0x08FF),
    (0xFB1D, 0xFDFF),
    (0xFE70, 0xFEFF),
)


def text_direction(text):
    for char in text or "":
        if _rtl_letter(char):
            return "rtl"
        if char.isascii() and char.isalpha():
            return "ltr"
    return "ltr"


def message_view(text):
    """Plain markdown for English. Rendered HTML for a right-to-left message."""
    body = plain_formulas(text or "")
    if text_direction(body) != "rtl":
        return "markdown", body
    html = markdown.markdown(body, extensions=["extra", "sane_lists"])
    return "html", f'<div dir="rtl">{html}</div>'


def plain_formulas(text):
    """Show a chemical formula as plain characters, in one left-to-right run."""
    parts = _CODE_SPAN.split(text)
    rendered = []
    for index, part in enumerate(parts):
        if index % 2 == 1:
            inner = part[1:-1]
            shown = readable_formula(_unwrap_math(inner))
            rendered.append(f"`{shown if shown else inner}`")
        else:
            part = _MATH.sub(_math_to_code, part)
            part = _BARE_FORMULA.sub(lambda match: f"`{match.group(1)}`", part)
            rendered.append(part)
    return "".join(rendered)


def readable_formula(src):
    text = src.strip()
    text = re.sub(r"\\[A-Za-z]+", "", text)
    text = text.replace("{", "").replace("}", "").replace("_", "").replace("^", "")
    text = text.replace("−", "-").replace(" ", "")
    if re.fullmatch(r"[+-]+[A-Z][A-Za-z0-9]+", text):
        split = len(text) - len(text.lstrip("+-"))
        text = text[split:] + text[:split]
    if re.fullmatch(r"[A-Z][A-Za-z0-9]*[+-]*", text) and any(char.isdigit() for char in text):
        return text
    return None


def _math_to_code(match):
    src = match.group(1) if match.group(1) is not None else match.group(2)
    shown = readable_formula(src)
    if not shown:
        return match.group(0)
    return f"`{shown}`"


def _unwrap_math(inner):
    text = inner.strip()
    if text.startswith("$$") and text.endswith("$$") and len(text) > 4:
        return text[2:-2]
    if text.startswith("$") and text.endswith("$") and len(text) > 2:
        return text[1:-1]
    return text


def _rtl_letter(char):
    code = ord(char)
    return any(start <= code <= end for start, end in _RTL_START)
