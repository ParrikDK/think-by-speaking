"""Library-based romanization for Mandarin (pinyin) and Cantonese (jyutping)."""
import re
from pypinyin import pinyin, Style

def _extract_chinese(text):
    return "".join(c for c in text if '一' <= c <= '鿿' or '㐀' <= c <= '䶿')

def _to_pinyin(text):
    if not text: return ""
    try:
        result = pinyin(text, style=Style.TONE)
        return " ".join(item[0] for item in result)
    except Exception:
        return ""

def _to_jyutping(text):
    if not text: return ""
    chinese_only = _extract_chinese(text)
    if not chinese_only: return ""
    try:
        import pycantonese
        result = pycantonese.characters_to_jyutping(chinese_only)
        return " ".join(j for _, j in result if j)
    except Exception:
        return ""

def _romanize_inline(text, language):
    converter = _to_pinyin if language in ("zh", "zh-tw", "zh-TW") else _to_jyutping
    parts = []; buf = []
    for c in text:
        if '一' <= c <= '鿿' or '㐀' <= c <= '䶿':
            buf.append(c)
        else:
            if buf: parts.append(converter(''.join(buf))); buf = []
            parts.append(c)
    if buf: parts.append(converter(''.join(buf)))
    result = ''.join(parts)
    result = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', result)
    return result

def _strip_annotations(text):
    anchor = r'([一-鿿㐀-䶿])'
    sep = r'[\s\'‘’\""]*'
    text = re.sub(rf'{anchor}{sep}\([^)]*\)', r'\1', text)
    text = re.sub(rf'{anchor}{sep}\[[^]]*\]', r'\1', text)
    return text

def romanize(text, language):
    if not text or not language: return ""
    lang = language.lower()
    if lang not in ("zh", "zh-tw", "yue"): return ""
    clean = _strip_annotations(text)
    return _romanize_inline(clean, lang)
