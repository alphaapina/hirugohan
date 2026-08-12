from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from curl_cffi import requests as browser_requests
from bs4 import BeautifulSoup, Tag

TZ = ZoneInfo("Europe/Helsinki")

RESTAURANTS = [
    {
        "name": "Antell Aino",
        "chain": "Antell",
        "url": "https://antell.fi/lounas/turku/aino/",
    },
    {
        "name": "Antell Joukahainen",
        "chain": "Antell",
        "url": "https://antell.fi/lounas/turku/joukahainen/",
    },
    {
        "name": "Antell Energeia",
        "chain": "Antell",
        "url": "https://antell.fi/lounas/turku/energeia/",
    },
    {
        "name": "Pegasus Kupittaanpuisto",
        "chain": "Pegasus",
        "url": "https://www.pegasus-ravintolat.fi/pegasus-kupittaanpuisto",
    },
    {
        "name": "Pegasus Lemminkäinen",
        "chain": "Pegasus",
        "url": "https://www.pegasus-ravintolat.fi/lemminkainen",
    },
    {
        "name": "Mauno TriviumCity",
        "chain": "Mauno",
        "url": "https://www.mauno.fi/lounaslistat/",
        "address": "Lemminkäisenkatu 32",
    },
]

# All locations on the shared Mauno page. ElectroCity is not displayed by this
# app, but it is needed as a section boundary between BioCity and TriviumCity.
MAUNO_ADDRESSES = [
    "Tykistökatu 6",
    "Tykistökatu 4",
    "Lemminkäisenkatu 32",
]

HEADERS = {
    "User-Agent": "TurkuLunch/0.2 (+https://github.com/)",
    "Accept-Language": "fi,en;q=0.8",
}

PRICE_RE = re.compile(r"^\d{1,3}(?:[.,]\d{1,2})?\s*€$")
DATE_FULL_RE = re.compile(
    r"^(?:MAANANTAI|TIISTAI|KESKIVIIKKO|TORSTAI|PERJANTAI|LAUANTAI|SUNNUNTAI)"
    r"\s+\d{1,2}\.\d{1,2}\.\d{4}$",
    re.I,
)
DATE_SHORT_RE = re.compile(
    r"^(?:Ma|Ti|Ke|To|Pe|La|Su)\s+\d{1,2}\.\d{1,2}$",
    re.I,
)
MAUNO_DATE_RE = re.compile(
    r"^(?:Maanantai|Tiistai|Keskiviikko|Torstai|Perjantai|Lauantai|Sunnuntai)"
    r"\s+\d{1,2}\.\d{1,2}\.\d{4}$",
    re.I,
)

ANTELL_CATEGORIES = {
    "Pääruoaksi",
    "Pääruoan kaveriksi",
    "Jälkiruoaksi",
    "Deli-lounas",
    "Salaattilounas",
}

ANTELL_BUTTON_EXCLUDES = {
    "×",
    "Miltä maistui?",
    "Luomukahvi",
    "Tumma Juhla Mokka-kahvi",
}

MAUNO_CATEGORIES = {
    "Buffet",
    "Kasvisruoka",
    "Vegaaninen lautasannos",
    "Avokeittiö",
    "Street food",
    "Street Food",
    "Ruokaisa annossalaatti",
    "Päivän annossalaatti",
    "Salaattibuffetin lämmin lisuke",
    "Jälkiruoka",
}


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def helsinki_date():
    return datetime.now(TZ).date()


def fetch(session: requests.Session, url: str) -> str:
    # Mauno serves a browser-verification page to plain Python requests.
    # Use a Chrome-like TLS/HTTP fingerprint only for Mauno.
    if "mauno.fi" in url:
        response = browser_requests.get(
            url,
            impersonate="chrome",
            timeout=20,
            headers={"Accept-Language": "fi,en;q=0.8"},
        )
        response.raise_for_status()
        html = response.text

        # Fail clearly if the anti-bot page is still returned.
        lower = html.casefold()
        if (
            "please wait while your request is being verified" in lower
            or "just a moment" in lower
            or "cf-chl-" in lower
        ):
            raise RuntimeError("Mauno returned browser-verification page")
        return html

    response = session.get(url, timeout=20)
    response.raise_for_status()
    return response.text


def block_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    lines = []
    for el in soup.select("h1,h2,h3,h4,h5,h6,p,li"):
        text = clean(el.get_text(" ", strip=True))
        if text and (not lines or lines[-1] != text):
            lines.append(text)
    return lines


def parse_antell(html: str, restaurant: dict, date) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # Use document-order element stream. Exact element text avoids matching
    # introductory prose that merely contains the word "Lounasbuffet".
    stream: list[Tag] = [
        el for el in soup.body.descendants
        if isinstance(el, Tag)
    ] if soup.body else []

    buffet_markers = [
        i for i, el in enumerate(stream)
        if clean(el.get_text(" ", strip=True)) == "Lounasbuffet"
        and clean(" ".join(el.find_all(string=True, recursive=False))) == "Lounasbuffet"
    ]

    if date.weekday() > 4:
        return result_base(restaurant, [])

    if len(buffet_markers) < 5:
        raise ValueError(
            f"Antell: expected at least 5 weekday buffet blocks, found {len(buffet_markers)}"
        )

    start = buffet_markers[date.weekday()]
    end = buffet_markers[date.weekday() + 1] if date.weekday() + 1 < len(buffet_markers) else len(stream)

    items = []
    seen = set()
    category = None

    for el in stream[start + 1:end]:
        tag = el.name.lower() if el.name else ""
        text = clean(el.get_text(" ", strip=True))

        if tag == "h5" and text in ANTELL_CATEGORIES:
            category = text
            continue

        if tag != "button" or not category:
            continue

        if not text or text in ANTELL_BUTTON_EXCLUDES:
            continue
        if re.match(r"^(?:avaa|sulje|close|menu)$", text, re.I):
            continue

        key = (category, text)
        if key in seen:
            continue
        seen.add(key)
        items.append({"category": category, "dish": text})

    return result_base(restaurant, items)


def find_pegasus_date_line(lines: list[str], date) -> int:
    long_days = [
        "MAANANTAI", "TIISTAI", "KESKIVIIKKO", "TORSTAI",
        "PERJANTAI", "LAUANTAI", "SUNNUNTAI",
    ]
    short_days = ["Ma", "Ti", "Ke", "To", "Pe", "La", "Su"]

    full = f"{long_days[date.weekday()]} {date.day}.{date.month}.{date.year}".casefold()
    short = f"{short_days[date.weekday()]} {date.day}.{date.month}".casefold()

    for i, line in enumerate(lines):
        if line.casefold() in {full, short}:
            return i
    return -1


def parse_pegasus(html: str, restaurant: dict, date) -> dict:
    lines = block_lines(html)
    start = find_pegasus_date_line(lines, date)
    if start < 0:
        return result_base(restaurant, [])

    items = []
    diet_re = re.compile(r"\((?:[^()]*(?:L|VL|G|M|V)[^()]*)\)\s*$", re.I)

    for line in lines[start + 1:]:
        if DATE_FULL_RE.match(line) or DATE_SHORT_RE.match(line) or line == "***":
            break
        if diet_re.search(line):
            items.append({"category": "Lounas", "dish": line})

    return result_base(restaurant, items)


def mauno_wanted_date(date) -> str:
    days = [
        "Maanantai", "Tiistai", "Keskiviikko", "Torstai",
        "Perjantai", "Lauantai", "Sunnuntai",
    ]
    return f"{days[date.weekday()]} {date.day}.{date.month}.{date.year}"


def parse_mauno(html: str, restaurant: dict, date) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # Mauno's wrapper tags vary, but the ordered text nodes are stable:
    # address -> weekday -> category -> dish -> price.
    lines = [clean(s) for s in soup.stripped_strings if clean(s)]

    address = restaurant["address"]

    address_index = next(
        (i for i, line in enumerate(lines) if line.startswith(address)),
        -1,
    )
    if address_index < 0:
        raise ValueError(f"Mauno: restaurant address not found: {address}")

    # Shared page order:
    # BioCity (Tykistökatu 6) -> ElectroCity (Tykistökatu 4)
    # -> TriviumCity (Lemminkäisenkatu 32).
    section_end = len(lines)
    for i in range(address_index + 1, len(lines)):
        if any(
            other != address and lines[i].startswith(other)
            for other in MAUNO_ADDRESSES
        ):
            section_end = i
            break

    section = lines[address_index:section_end]

    wanted = mauno_wanted_date(date).casefold()
    start = next(
        (i for i, line in enumerate(section) if line.casefold() == wanted),
        -1,
    )
    if start < 0:
        return result_base(restaurant, [])

    items = []
    category = None

    for line in section[start + 1:]:
        # The next weekday starts the next day's menu.
        if MAUNO_DATE_RE.match(line):
            break

        if line.startswith("Hävikkiruoan myynti"):
            continue

        if line in MAUNO_CATEGORIES:
            category = line
            continue

        if not category:
            continue

        if PRICE_RE.match(line):
            continue

        items.append({
            "category": category,
            "dish": line,
            **(
                {"unavailable": True}
                if re.match(r"^(?:Kesätauolla!|Loppu)$", line, re.I)
                else {}
            ),
        })
        category = None

    return result_base(restaurant, items)

def result_base(restaurant: dict, items: list[dict]) -> dict:
    items = [
        item for item in items
        if clean(item.get("dish")) != "Katso lisätiedot"
    ]
    return {
        "name": restaurant["name"],
        "chain": restaurant["chain"],
        "source": restaurant["url"],
        "items": items,
    }


def scrape_all() -> dict:
    date = helsinki_date()
    session = requests.Session()
    session.headers.update(HEADERS)

    # Fetch each unique URL only once. Mauno's two restaurants share a page.
    fetched: dict[str, str] = {}
    fetch_errors: dict[str, str] = {}

    for url in dict.fromkeys(r["url"] for r in RESTAURANTS):
        try:
            fetched[url] = fetch(session, url)
        except Exception as exc:
            fetch_errors[url] = f"{type(exc).__name__}: {exc}"

    restaurants = []

    for restaurant in RESTAURANTS:
        url = restaurant["url"]

        if url in fetch_errors:
            restaurants.append({
                **result_base(restaurant, []),
                "error": fetch_errors[url],
            })
            continue

        try:
            if restaurant["chain"] == "Antell":
                parsed = parse_antell(fetched[url], restaurant, date)
            elif restaurant["chain"] == "Pegasus":
                parsed = parse_pegasus(fetched[url], restaurant, date)
            else:
                parsed = parse_mauno(fetched[url], restaurant, date)
            restaurants.append(parsed)
        except Exception as exc:
            restaurants.append({
                **result_base(restaurant, []),
                "error": f"{type(exc).__name__}: {exc}",
            })

    return {
        "date": date.isoformat(),
        "generatedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "restaurants": restaurants,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(scrape_all(), ensure_ascii=False, indent=2))
