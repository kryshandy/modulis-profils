"""vCard 3.0 (RFC 2426) for « Enregistrer le contact »."""

from __future__ import annotations

from apps.seo.meta import clean_text

CRLF = "\r\n"
FOLD_OCTETS = 75


def escape(value: str) -> str:
    """Escape a text value: backslash, comma, semicolon and newlines (RFC 2426 §4)."""
    value = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    return value.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def fold(line: str) -> str:
    """Fold a content line at 75 octets without splitting a UTF-8 character."""
    parts, current, size = [], "", 0
    limit = FOLD_OCTETS
    for char in line:
        width = len(char.encode())
        if size + width > limit:
            parts.append(current)
            current, size = "", 0
            limit = FOLD_OCTETS - 1  # continuation lines start with one space
        current += char
        size += width
    parts.append(current)
    return (CRLF + " ").join(parts)


def build_vcard(profile, *, url: str) -> str:
    name = clean_text(profile.display_name)
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{escape(name)}"]
    if profile.kind == "business":
        lines += [f"N:{escape(name)};;;;", f"ORG:{escape(name)}"]
    else:
        lines.append(f"N:;{escape(name)};;;")
    if profile.title:
        lines.append(f"TITLE:{escape(clean_text(profile.title))}")
    if profile.phone_public:
        lines.append(f"TEL;TYPE=CELL,VOICE:{escape(profile.phone_public)}")
    if profile.whatsapp and profile.whatsapp != profile.phone_public:
        lines.append(f"TEL;TYPE=CELL:{escape(profile.whatsapp)}")
    if profile.email_public:
        lines.append(f"EMAIL;TYPE=INTERNET:{escape(profile.email_public)}")
    if profile.city or profile.address:
        city = profile.city.name if profile.city else ""
        country = profile.city.country.name if profile.city else ""
        street = clean_text(profile.address)
        lines.append(f"ADR;TYPE=WORK:;;{escape(street)};{escape(city)};;;{escape(country)}")
    lines.append(f"URL:{url}")  # URI value type: not text-escaped
    bio = clean_text(profile.bio)
    if bio:
        lines.append(f"NOTE:{escape(bio[:500])}")
    lines.append("END:VCARD")
    return CRLF.join(fold(line) for line in lines) + CRLF
