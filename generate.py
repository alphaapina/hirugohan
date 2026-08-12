from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from scraper import scrape_all

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "public"


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def build_page(data: dict) -> str:
    css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")

    date_label = datetime.fromisoformat(data["date"]).strftime("%d.%m.%Y")
    generated = datetime.fromisoformat(data["generatedAt"])
    generated_label = generated.strftime("%H:%M")

    cards = []

    for restaurant in data["restaurants"]:
        body = []

        if restaurant.get("error"):
            body.append(
                f'<p class="error">{esc(restaurant["error"])}</p>'
            )
        elif not restaurant.get("items"):
            body.append(
                '<p class="empty">Ei lounaslistaa tälle päivälle.</p>'
            )
        else:
            current_category = None
            opened_list = False

            for item in restaurant["items"]:
                category = item.get("category", "")

                if category != current_category:
                    if opened_list:
                        body.append("</ul>")
                    current_category = category
                    body.append(f"<h3>{esc(category)}</h3>")
                    body.append("<ul>")
                    opened_list = True

                cls = ' class="unavailable"' if item.get("unavailable") else ""
                body.append(f"<li{cls}>{esc(item.get('dish', ''))}</li>")

            if opened_list:
                body.append("</ul>")

        cards.append(
            '<article class="card">'
            '<div class="card-heading">'
            f'<h2>{esc(restaurant["name"])}</h2>'
            f'<a href="{esc(restaurant["source"])}" target="_blank" rel="noreferrer">lähde</a>'
            '</div>'
            + "".join(body)
            + '</article>'
        )

    good = sum(
        1 for r in data["restaurants"]
        if not r.get("error") and r.get("items")
    )

    count = len(data["restaurants"])

    return f"""<!doctype html>
<html lang="fi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title></title>
  <style>
{css}
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <h1>Kuppis lunch</h1>
        <p class="meta">{esc(date_label)} · {good}/{count} ravintolaa · päivitetty {esc(generated_label)}</p>
      </div>
    </header>

    <section class="grid">
      {"".join(cards)}
    </section>
  </main>
</body>
</html>
"""


def main() -> None:
    data = scrape_all()
    OUT.mkdir(parents=True, exist_ok=True)

    (OUT / "index.html").write_text(
        build_page(data),
        encoding="utf-8",
    )

    (OUT / "menus.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    failures = [r for r in data["restaurants"] if r.get("error")]
    print(
        f"Generated {OUT / 'index.html'}: "
        f"{len(data['restaurants']) - len(failures)}/{len(data['restaurants'])} without fetch/parser errors"
    )
    for r in failures:
        print(f"ERROR {r['name']}: {r['error']}")


if __name__ == "__main__":
    main()
