"""Real-time Masters leaderboard web app.

Starts a local HTTP server that displays a live Masters leaderboard page.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCORES_URL = "https://www.masters.com/en_US/scores/feeds/2026/scores.json"


def fetch_scores(url: str, timeout: int) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Masters Leaderboard Web)",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def normalize_value(value: Any, default: str = "-") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def parse_score_to_int(text: Any) -> int | None:
    if text is None:
        return None
    s = str(text).strip().upper()
    if not s:
        return None
    if s == "E":
        return 0
    try:
        return int(s)
    except ValueError:
        return None


def parse_cut_line(cut_text: Any) -> int | None:
    return parse_score_to_int(cut_text)


def parse_current_round(data: dict[str, Any]) -> int:
    marker = str(data.get("currentRound", "")).strip()
    if len(marker) >= 4 and marker.isdigit():
        for idx, char in enumerate(marker[:4], start=1):
            if char == "1":
                return idx
    return 1


def pick_player_round(player: dict[str, Any], fallback_round: int) -> int:
    for round_num in range(1, 5):
        round_data = player.get(f"round{round_num}", {})
        if normalize_value(round_data.get("roundStatus"), default="").lower() == "playing":
            return round_num

    for round_num in range(4, 0, -1):
        round_data = player.get(f"round{round_num}", {})
        scores = round_data.get("scores", [])
        if any(isinstance(score, int) for score in scores):
            return round_num

    return fallback_round


def extract_rows(payload: dict[str, Any], top_n: int) -> dict[str, Any]:
    data = payload.get("data", {})
    updated = normalize_value(data.get("wallClockTime"), default="Unknown")
    cut_line_text = normalize_value(data.get("cutLine"), default="-")
    cut_line_numeric = parse_cut_line(cut_line_text)
    players = data.get("player", [])
    pars = data.get("pars", {})
    current_round = parse_current_round(data)

    rows: list[dict[str, Any]] = []
    daily_values: list[tuple[int, str]] = []

    for player in players:
        position = normalize_value(player.get("pos"))
        name = normalize_value(player.get("full_name"), default="Unknown Player")
        total_to_par = normalize_value(player.get("topar"))
        today = normalize_value(player.get("today"))
        thru = normalize_value(player.get("thru"))
        status = normalize_value(player.get("status"))
        player_id = normalize_value(player.get("id"), default=name)

        if position == "-" and total_to_par == "-":
            continue

        player_round = pick_player_round(player, current_round)
        active_round_data = player.get(f"round{player_round}", {})
        round_scores = active_round_data.get("scores", [])
        if not isinstance(round_scores, list):
            round_scores = []

        holes: list[dict[str, Any]] = []
        par_values = pars.get(f"round{player_round}", [])
        for hole_number in range(1, 19):
            score = round_scores[hole_number - 1] if hole_number - 1 < len(round_scores) else None
            par = par_values[hole_number - 1] if hole_number - 1 < len(par_values) else None
            holes.append(
                {
                    "hole": hole_number,
                    "score": score,
                    "par": par,
                }
            )

        today_numeric = parse_score_to_int(today)
        if today_numeric is not None:
            daily_values.append((today_numeric, player_id))

        rows.append(
            {
                "id": player_id,
                "position": position,
                "name": name,
                "total_to_par": total_to_par,
                "today": today,
                "thru": thru,
                "status": status,
                "today_numeric": today_numeric,
                "round": player_round,
                "round_status": normalize_value(active_round_data.get("roundStatus"), default="-"),
                "holes": holes,
            }
        )

    rows.sort(key=lambda r: r["position"].replace("T", "Z") + r["name"])
    top_rows = rows[:top_n]

    best_today_ids = [pid for _, pid in sorted(daily_values, key=lambda item: item[0])[:3]]
    worst_today_ids = [pid for _, pid in sorted(daily_values, key=lambda item: item[0], reverse=True)[:3]]
    best_round_ids: list[str] = []
    worst_round_ids: list[str] = []
    if daily_values:
      best_round_score = min(score for score, _ in daily_values)
      best_round_ids = [pid for score, pid in daily_values if score == best_round_score]
      worst_round_score = max(score for score, _ in daily_values)
      worst_round_ids = [pid for score, pid in daily_values if score == worst_round_score]

    row_by_id = {str(r["id"]): r for r in rows}
    best_today_players = [
      {
        "id": pid,
        "name": row_by_id.get(str(pid), {}).get("name", "-"),
        "position": row_by_id.get(str(pid), {}).get("position", "-"),
        "today": row_by_id.get(str(pid), {}).get("today", "-"),
        "total_to_par": row_by_id.get(str(pid), {}).get("total_to_par", "-"),
      }
      for pid in best_today_ids
    ]
    worst_today_players = [
      {
        "id": pid,
        "name": row_by_id.get(str(pid), {}).get("name", "-"),
        "position": row_by_id.get(str(pid), {}).get("position", "-"),
        "today": row_by_id.get(str(pid), {}).get("today", "-"),
        "total_to_par": row_by_id.get(str(pid), {}).get("total_to_par", "-"),
      }
      for pid in worst_today_ids
    ]

    current_round_pars = pars.get(f"round{current_round}", [])
    hole_buckets: list[list[int]] = [[] for _ in range(18)]

    for row in rows:
        if row["round"] != current_round:
            continue
        for idx, hole_info in enumerate(row["holes"]):
            score = hole_info.get("score")
            if isinstance(score, int):
                hole_buckets[idx].append(score)

    hole_averages: list[dict[str, Any]] = []
    for idx in range(18):
        samples = hole_buckets[idx]
        avg_score = (sum(samples) / len(samples)) if samples else None
        par = current_round_pars[idx] if idx < len(current_round_pars) else None
        hole_averages.append(
            {
                "hole": idx + 1,
                "average": round(avg_score, 2) if avg_score is not None else None,
                "samples": len(samples),
                "par": par,
            }
        )

    valid_hole_avgs = [h for h in hole_averages if h["average"] is not None]
    easiest_holes = [h["hole"] for h in sorted(valid_hole_avgs, key=lambda h: h["average"])[:3]]
    hardest_holes = [h["hole"] for h in sorted(valid_hole_avgs, key=lambda h: h["average"], reverse=True)[:3]]

    return {
        "updated": updated,
        "cut_line": cut_line_text,
        "cut_line_numeric": cut_line_numeric,
        "current_round": current_round,
        "rows": top_rows,
      "all_rows": rows,
        "best_today_ids": best_today_ids,
        "worst_today_ids": worst_today_ids,
        "best_round_ids": best_round_ids,
        "worst_round_ids": worst_round_ids,
        "best_today_players": best_today_players,
        "worst_today_players": worst_today_players,
        "hole_averages": hole_averages,
        "easiest_holes": easiest_holes,
        "hardest_holes": hardest_holes,
        "local_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def render_index_html(top_n: int) -> str:
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>The Masters Leaderboard</title>
  <style>
    :root {{
      --bg: #f0efe9;
      --ink: #1b2a1d;
      --muted: #5d6b61;
      --panel: #ffffff;
      --line: #d9e2d9;
      --accent: #0e5d31;
      --best: #e5f6e5;
      --worst: #fde8e8;
      --hole-best: #e8f7ec;
      --hole-worst: #fff0db;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, Cambria, "Times New Roman", serif;
      color: var(--ink);
      background: radial-gradient(900px 400px at 90% -10%, #deeadf, var(--bg));
    }}
    .container {{
      width: min(1200px, 94vw);
      margin: 24px auto 30px;
      display: grid;
      gap: 18px;
    }}
    .hero {{
      background: linear-gradient(130deg, #0f5d31, #2b7d4a);
      border-radius: 14px;
      padding: 16px 18px;
      color: #f6fbf6;
      box-shadow: 0 8px 28px rgba(0, 0, 0, 0.14);
    }}
    .hero h1 {{ margin: 0; font-size: 1.35rem; }}
    .hero p {{ margin: 8px 0 0; opacity: 0.95; font-size: 0.95rem; }}
    .grid {{
      display: grid;
      grid-template-columns: 2.1fr 1fr;
      gap: 18px;
    }}
    .side-stack {{
      display: grid;
      gap: 18px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
      box-shadow: 0 8px 24px rgba(28, 45, 31, 0.08);
    }}
    .card-head {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .card-head h2 {{ margin: 0; font-size: 1.02rem; }}
    .meta {{ color: var(--muted); font-size: 0.86rem; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid #edf2ed;
      font-size: 0.95rem;
    }}
    th {{
      text-align: left;
      color: var(--muted);
      font-size: 0.8rem;
      letter-spacing: 0.07em;
    }}
    .sort-btn {{
      appearance: none;
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      letter-spacing: inherit;
      cursor: pointer;
      padding: 0;
    }}
    .sort-btn::after {{
      content: '  <>';
      font-size: 0.72rem;
      opacity: 0.6;
    }}
    .sort-btn.active.asc::after {{ content: '  ^'; opacity: 1; }}
    .sort-btn.active.desc::after {{ content: '  v'; opacity: 1; }}
    td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .clickable {{ cursor: pointer; }}
    .clickable:hover {{ background: #f6fbf7; }}
    .highlight-best-round {{ background: #bfeccc; }}
    .highlight-worst-round {{ background: #f7b9b9; }}
    .highlight-best {{ background: var(--best); }}
    .highlight-worst {{ background: var(--worst); }}
    .cut-line-row td {{
      padding: 6px 10px;
      background: #fff7df;
      color: #6f5a1d;
      border-top: 2px solid #d8b34e;
      border-bottom: 2px solid #d8b34e;
      font-size: 0.82rem;
      letter-spacing: 0.05em;
      text-align: center;
      font-weight: 700;
    }}
    .legend {{
      padding: 10px 14px;
      border-top: 1px solid var(--line);
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      font-size: 0.82rem;
      color: var(--muted);
    }}
    .chip {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 9px;
      background: #fafdfa;
      cursor: pointer;
    }}
    .chip.active {{
      border-color: #9cb49f;
      box-shadow: inset 0 0 0 1px #9cb49f;
    }}
    .chip.best {{ background: var(--best); }}
    .chip.worst {{ background: var(--worst); }}
    .chip.hole-best {{ background: var(--hole-best); }}
    .chip.hole-worst {{ background: var(--hole-worst); }}
    .top3-wrap {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      padding: 12px;
    }}
    .top3-group {{
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fbfdfb;
      overflow: hidden;
    }}
    .top3-title {{
      margin: 0;
      padding: 8px 10px;
      font-size: 0.82rem;
      letter-spacing: 0.06em;
      color: var(--muted);
      border-bottom: 1px solid var(--line);
    }}
    .top3-title.best {{ background: var(--best); }}
    .top3-title.worst {{ background: var(--worst); }}
    .top3-list {{
      list-style: none;
      margin: 0;
      padding: 0;
    }}
    .top3-list li {{
      display: grid;
      grid-template-columns: 26px 1fr auto;
      gap: 8px;
      padding: 8px 10px;
      border-bottom: 1px solid #eef2ee;
      font-size: 0.9rem;
      align-items: center;
    }}
    .top3-list li:last-child {{ border-bottom: 0; }}
    .top3-rank {{ color: var(--muted); font-size: 0.82rem; }}
    .top3-score {{ font-variant-numeric: tabular-nums; font-weight: 600; }}
    .hole-best {{ background: var(--hole-best); }}
    .hole-worst {{ background: var(--hole-worst); }}
    .error {{
      display: none;
      margin-top: 8px;
      background: #fff2f2;
      border: 1px solid #f1cccc;
      color: #8c1e1e;
      border-radius: 10px;
      padding: 8px 10px;
      font-size: 0.9rem;
    }}
    .modal-backdrop {{
      position: fixed;
      inset: 0;
      background: rgba(10, 20, 15, 0.45);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 12px;
      z-index: 50;
    }}
    .modal {{
      width: min(960px, 96vw);
      max-height: 88vh;
      overflow: auto;
      background: #fff;
      border-radius: 14px;
      border: 1px solid var(--line);
      box-shadow: 0 16px 40px rgba(18, 28, 20, 0.22);
    }}
    .modal-head {{
      position: sticky;
      top: 0;
      background: #fff;
      border-bottom: 1px solid var(--line);
      padding: 10px 14px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .close-btn {{
      border: 1px solid var(--line);
      background: #f7faf7;
      border-radius: 8px;
      padding: 6px 10px;
      cursor: pointer;
    }}
    .hole-grid {{
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 8px;
      padding: 12px;
    }}
    .hole-box {{
      border: 2px solid #cfd9cf;
      border-radius: 10px;
      padding: 8px;
      background: #fcfdfb;
      text-align: center;
    }}
    .hole-num {{ font-size: 0.75rem; color: var(--muted); letter-spacing: 0.07em; }}
    .hole-score {{ font-size: 1.06rem; font-weight: 600; margin-top: 4px; }}
    .hole-par {{ font-size: 0.82rem; color: var(--muted); margin-top: 2px; }}
    .under-par {{ background: #d9b8ff; border-color: #9050d8; }}
    .over-par {{ background: #ffcccc; border-color: #d74a4a; }}
    .at-par {{ background: #c9f0d1; border-color: #3a9d53; }}
    .hole-state {{
      margin-top: 4px;
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    @media (max-width: 980px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 760px) {{
      .hole-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
      .top3-wrap {{ grid-template-columns: 1fr; }}
      th:nth-child(6), td:nth-child(6) {{ display: none; }}
      th, td {{ padding: 8px 8px; font-size: 0.88rem; }}
    }}
  </style>
</head>
<body>
  <div class=\"container\">
    <section class=\"hero\">
      <h1>The Masters Leaderboard</h1>
      <p id=\"meta\">Loading...</p>
      <div id=\"error\" class=\"error\"></div>
    </section>

    <section class=\"grid\">
      <div class=\"side-stack\">
      <article class=\"card\">
        <div class=\"card-head\">
          <h2>Top 3 Today</h2>
          <div class=\"meta\">Lowest and highest round scores</div>
        </div>
        <div class=\"top3-wrap\">
          <section class=\"top3-group\">
            <h3 class=\"top3-title best\">Lowest Today</h3>
            <ul id=\"top3-best\" class=\"top3-list\"></ul>
          </section>
          <section class=\"top3-group\">
            <h3 class=\"top3-title worst\">Highest Today</h3>
            <ul id=\"top3-worst\" class=\"top3-list\"></ul>
          </section>
        </div>
      </article>

      <article class=\"card\">
        <div class=\"card-head\">
          <h2>Leaderboard (click a player)</h2>
          <div class=\"meta\">All players available</div>
        </div>
        <table>
          <thead>
            <tr>
              <th><button class=\"sort-btn active asc\" data-table=\"players\" data-key=\"position\" type=\"button\">POS</button></th>
              <th><button class=\"sort-btn\" data-table=\"players\" data-key=\"name\" type=\"button\">PLAYER</button></th>
              <th class=\"num\"><button class=\"sort-btn\" data-table=\"players\" data-key=\"total_to_par\" type=\"button\">TOTAL</button></th>
              <th class=\"num\"><button class=\"sort-btn\" data-table=\"players\" data-key=\"today\" type=\"button\">TODAY</button></th>
              <th class=\"num\"><button class=\"sort-btn\" data-table=\"players\" data-key=\"thru\" type=\"button\">THRU</button></th>
              <th><button class=\"sort-btn\" data-table=\"players\" data-key=\"status\" type=\"button\">STATUS</button></th>
            </tr>
          </thead>
          <tbody id=\"rows\"></tbody>
        </table>
        <div class=\"legend\">
          <button id=\"filter-all\" class=\"chip active\" type=\"button\">Show all</button>
          <button id=\"filter-best\" class=\"chip best\" type=\"button\">Top 3 lowest today</button>
          <button id=\"filter-worst\" class=\"chip worst\" type=\"button\">Top 3 highest today</button>
        </div>
      </article>

      <article class=\"card\">
        <div class=\"card-head\">
          <h2>Hole Averages (Separate Window)</h2>
          <div>
            <button id=\"popout-btn\" class=\"close-btn\" type=\"button\">Open Pop-Out</button>
          </div>
        </div>
        <div id=\"hole-filter-status\" class=\"meta\" style=\"padding:8px 12px 0\">Currently showing: All holes</div>
        <table>
          <thead>
            <tr>
              <th class=\"num\"><button class=\"sort-btn active asc\" data-table=\"holes\" data-key=\"hole\" type=\"button\">HOLE</button></th>
              <th class=\"num\"><button class=\"sort-btn\" data-table=\"holes\" data-key=\"par\" type=\"button\">PAR</button></th>
              <th class=\"num\"><button class=\"sort-btn\" data-table=\"holes\" data-key=\"average\" type=\"button\">AVG</button></th>
              <th class=\"num\"><button class=\"sort-btn\" data-table=\"holes\" data-key=\"samples\" type=\"button\">SAMPLES</button></th>
            </tr>
          </thead>
          <tbody id=\"hole-rows\"></tbody>
        </table>
        <div class=\"legend\">
          <button id=\"hole-filter-all\" class=\"chip active\" type=\"button\">Show all holes</button>
          <button id=\"hole-filter-worst\" class=\"chip hole-worst\" type=\"button\">Top 3 highest avg</button>
          <button id=\"hole-filter-best\" class=\"chip hole-best\" type=\"button\">Top 3 lowest avg</button>
        </div>
      </article>
      </div>
    </section>
  </div>

  <div id=\"player-modal\" class=\"modal-backdrop\" role=\"dialog\" aria-modal=\"true\">
    <div class=\"modal\">
      <div class=\"modal-head\">
        <div>
          <strong id=\"modal-title\">Player</strong>
          <div id=\"modal-subtitle\" class=\"meta\"></div>
        </div>
        <button id=\"close-modal\" class=\"close-btn\" type=\"button\">Close</button>
      </div>
      <div id=\"hole-grid\" class=\"hole-grid\"></div>
    </div>
  </div>

  <script>
    const refreshMs = 60000;
    let latestRows = [];
    let holeWindow = null;
    let filterMode = 'all';
    let latestData = null;
    let holeFilterMode = 'all';
    let playerSort = {{ key: 'total_to_par', dir: 'asc' }};
    let holeSort = {{ key: 'average', dir: 'desc' }};

    function esc(text) {{
      return String(text)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;');
    }}

    function formatAvg(avg) {{
      return avg === null || avg === undefined ? '-' : Number(avg).toFixed(2);
    }}

    function parseGolfScore(value) {{
      if (value === null || value === undefined) return null;
      const text = String(value).trim().toUpperCase();
      if (!text) return null;
      if (text === 'E') return 0;
      const num = Number(text);
      return Number.isNaN(num) ? null : num;
    }}

    function insertCutLine(rowsHtmlParts, visibleRows, cutLineText, cutLineNumeric) {{
      if (cutLineNumeric === null || cutLineNumeric === undefined) return rowsHtmlParts.join('');

      let inserted = false;
      const out = [];
      for (let i = 0; i < visibleRows.length; i++) {{
        const row = visibleRows[i];
        const total = parseGolfScore(row.total_to_par);
        if (!inserted && total !== null && total > cutLineNumeric) {{
          out.push(`<tr class="cut-line-row"><td colspan="6">PROJECTED CUT LINE ${{esc(cutLineText)}}</td></tr>`);
          inserted = true;
        }}
        out.push(rowsHtmlParts[i]);
      }}
      if (!inserted && visibleRows.length) {{
        out.push(`<tr class="cut-line-row"><td colspan="6">PROJECTED CUT LINE ${{esc(cutLineText)}}</td></tr>`);
      }}
      return out.join('');
    }}

    function parsePosition(value) {{
      const text = String(value ?? '').replace('T', '').trim();
      const num = Number(text);
      return Number.isNaN(num) ? Number.MAX_SAFE_INTEGER : num;
    }}

    function parseThru(value) {{
      const text = String(value ?? '').trim().toUpperCase();
      if (!text) return Number.MAX_SAFE_INTEGER;
      if (text === 'F') return 99;
      const num = Number(text);
      return Number.isNaN(num) ? Number.MAX_SAFE_INTEGER : num;
    }}

    function compareValues(a, b, dir) {{
      if (a === null || a === undefined) return 1;
      if (b === null || b === undefined) return -1;
      if (typeof a === 'string' && typeof b === 'string') {{
        const cmp = a.localeCompare(b);
        return dir === 'asc' ? cmp : -cmp;
      }}
      const cmp = a < b ? -1 : a > b ? 1 : 0;
      return dir === 'asc' ? cmp : -cmp;
    }}

    function sortPlayerRows(rows) {{
      const key = playerSort.key;
      const dir = playerSort.dir;
      const valueOf = (row) => {{
        if (key === 'position') return parsePosition(row.position);
        if (key === 'name') return String(row.name ?? '').toLowerCase();
        if (key === 'total_to_par') return parseGolfScore(row.total_to_par);
        if (key === 'today') return parseGolfScore(row.today);
        if (key === 'thru') return parseThru(row.thru);
        if (key === 'status') return String(row.status ?? '').toLowerCase();
        return parsePosition(row.position);
      }};
      return [...rows].sort((a, b) => compareValues(valueOf(a), valueOf(b), dir));
    }}

    function sortHoleRows(holes) {{
      const key = holeSort.key;
      const dir = holeSort.dir;
      const valueOf = (h) => {{
        if (key === 'hole') return Number(h.hole);
        if (key === 'par') return h.par === null || h.par === undefined ? null : Number(h.par);
        if (key === 'average') return h.average === null || h.average === undefined ? null : Number(h.average);
        if (key === 'samples') return Number(h.samples ?? 0);
        return Number(h.hole);
      }};
      return [...holes].sort((a, b) => compareValues(valueOf(a), valueOf(b), dir));
    }}

    function updateSortButtons() {{
      document.querySelectorAll('.sort-btn').forEach((btn) => {{
        btn.classList.remove('active', 'asc', 'desc');
        const table = btn.getAttribute('data-table');
        const key = btn.getAttribute('data-key');
        if (table === 'players' && key === playerSort.key) btn.classList.add('active', playerSort.dir);
        if (table === 'holes' && key === holeSort.key) btn.classList.add('active', holeSort.dir);
      }});
    }}

    function rowClassForPlayer(row, bestRoundSet, worstRoundSet, bestSet, worstSet) {{
      if (bestRoundSet.has(row.id)) return 'highlight-best-round';
      if (worstRoundSet.has(row.id)) return 'highlight-worst-round';
      if (bestSet.has(row.id)) return 'highlight-best';
      if (worstSet.has(row.id)) return 'highlight-worst';
      return '';
    }}

    function renderTopThreePanel(data) {{
      const best = data.best_today_players || [];
      const worst = data.worst_today_players || [];
      const bestEl = document.getElementById('top3-best');
      const worstEl = document.getElementById('top3-worst');

      bestEl.innerHTML = best.map((p, i) => `
        <li>
          <span class="top3-rank">#${{i + 1}}</span>
          <span>${{esc(p.name)}} <span class="meta">(${{esc(p.position)}})</span></span>
          <span class="top3-score">${{esc(p.today)}}</span>
        </li>
      `).join('');

      worstEl.innerHTML = worst.map((p, i) => `
        <li>
          <span class="top3-rank">#${{i + 1}}</span>
          <span>${{esc(p.name)}} <span class="meta">(${{esc(p.position)}})</span></span>
          <span class="top3-score">${{esc(p.today)}}</span>
        </li>
      `).join('');
    }}

    function filterRows(rows, bestSet, worstSet) {{
      if (filterMode === 'best') return rows.filter((r) => bestSet.has(r.id));
      if (filterMode === 'worst') return rows.filter((r) => worstSet.has(r.id));
      return rows;
    }}

    function updateFilterButtons() {{
      const ids = ['filter-all', 'filter-best', 'filter-worst'];
      for (const id of ids) {{
        const el = document.getElementById(id);
        if (el) el.classList.remove('active');
      }}
      const map = {{ all: 'filter-all', best: 'filter-best', worst: 'filter-worst' }};
      const active = document.getElementById(map[filterMode]);
      if (active) active.classList.add('active');
    }}

    function updateHoleFilterButtons() {{
      const ids = ['hole-filter-all', 'hole-filter-best', 'hole-filter-worst'];
      for (const id of ids) {{
        const el = document.getElementById(id);
        if (el) el.classList.remove('active');
      }}
      const map = {{ all: 'hole-filter-all', best: 'hole-filter-best', worst: 'hole-filter-worst' }};
      const active = document.getElementById(map[holeFilterMode]);
      if (active) active.classList.add('active');

      const labels = {{ all: 'All holes', best: 'Top 3 lowest average holes', worst: 'Top 3 highest average holes' }};
      const status = document.getElementById('hole-filter-status');
      if (status) status.textContent = `Currently showing: ${{labels[holeFilterMode]}}`;
    }}

    function renderRows(data) {{
      const body = document.getElementById('rows');
      const bestRoundSet = new Set(data.best_round_ids || []);
      const worstRoundSet = new Set(data.worst_round_ids || []);
      const bestSet = new Set(data.best_today_ids || []);
      const worstSet = new Set(data.worst_today_ids || []);
      latestRows = data.all_rows || data.rows || [];
      const visibleRows = sortPlayerRows(filterRows(latestRows, bestSet, worstSet));
      updateFilterButtons();
      updateSortButtons();

      const rowHtml = visibleRows.map((r) => `
        <tr class="clickable ${{rowClassForPlayer(r, bestRoundSet, worstRoundSet, bestSet, worstSet)}}" data-player-id="${{esc(r.id)}}">
          <td>${{esc(r.position)}}</td>
          <td>${{esc(r.name)}}</td>
          <td class="num">${{esc(r.total_to_par)}}</td>
          <td class="num">${{esc(r.today)}}</td>
          <td class="num">${{esc(r.thru)}}</td>
          <td>${{esc(r.status)}}</td>
        </tr>
      `);

      body.innerHTML = insertCutLine(
        rowHtml,
        visibleRows,
        data.cut_line,
        data.cut_line_numeric
      );

      if (!visibleRows.length) {{
        body.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#5d6b61">No players in this filter.</td></tr>';
      }}
    }}

    function renderHoleAverages(data) {{
      const body = document.getElementById('hole-rows');
      const easiest = new Set(data.easiest_holes || []);
      const hardest = new Set(data.hardest_holes || []);
      const holes = data.hole_averages || [];
      let visibleHoles = holes;

      if (holeFilterMode === 'best') {{
        visibleHoles = holes.filter((h) => easiest.has(h.hole));
      }} else if (holeFilterMode === 'worst') {{
        visibleHoles = holes.filter((h) => hardest.has(h.hole));
      }}

      visibleHoles = sortHoleRows(visibleHoles);
      updateHoleFilterButtons();
      updateSortButtons();

      body.innerHTML = visibleHoles.map((h) => {{
        let cls = '';
        if (easiest.has(h.hole)) cls = 'hole-best';
        if (hardest.has(h.hole)) cls = 'hole-worst';

        return `
          <tr class="${{cls}}">
            <td class="num">${{esc(h.hole)}}</td>
            <td class="num">${{esc(h.par ?? '-')}}</td>
            <td class="num">${{esc(formatAvg(h.average))}}</td>
            <td class="num">${{esc(h.samples)}}</td>
          </tr>
        `;
      }}).join('');

      if (!visibleHoles.length) {{
        body.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#5d6b61">No holes in this filter.</td></tr>';
      }}
    }}

    function holeAveragesHtml(data) {{
      const easiest = new Set(data.easiest_holes || []);
      const hardest = new Set(data.hardest_holes || []);
      const rows = (data.hole_averages || []).map((h) => {{
        let cls = '';
        if (easiest.has(h.hole)) cls = 'background:#e8f7ec;';
        else if (hardest.has(h.hole)) cls = 'background:#fff0db;';
        const avg = h.average === null || h.average === undefined ? '-' : Number(h.average).toFixed(2);
        return `<tr style="${{cls}}"><td style="padding:6px 8px;text-align:right">${{h.hole}}</td><td style="padding:6px 8px;text-align:right">${{h.par ?? '-'}}</td><td style="padding:6px 8px;text-align:right">${{avg}}</td><td style="padding:6px 8px;text-align:right">${{h.samples}}</td></tr>`;
      }}).join('');

      return `<!doctype html><html><head><meta charset="utf-8"><title>Hole Averages</title><style>body{{font-family:Georgia,serif;padding:12px;background:#f7f6f1;color:#1b2a1d}} table{{width:100%;border-collapse:collapse;background:#fff}} th,td{{border:1px solid #d9e2d9;padding:6px 8px}} th{{font-size:12px;letter-spacing:.06em;color:#5d6b61}} h2{{margin:0 0 8px 0}} .meta{{color:#5d6b61;font-size:13px;margin-bottom:8px}}</style></head><body><h2>Hole Averages</h2><div class="meta">Round ${{data.current_round}} | Updated: ${{data.updated}}</div><table><thead><tr><th style="text-align:right">HOLE</th><th style="text-align:right">PAR</th><th style="text-align:right">AVG</th><th style="text-align:right">SAMPLES</th></tr></thead><tbody>${{rows}}</tbody></table></body></html>`;
    }}

    function updateHolePopout(data) {{
      if (!holeWindow || holeWindow.closed) return;
      holeWindow.document.open();
      holeWindow.document.write(holeAveragesHtml(data));
      holeWindow.document.close();
    }}

    function openHolePopout(latestData) {{
      if (!holeWindow || holeWindow.closed) {{
        holeWindow = window.open('', 'masters-hole-averages', 'width=640,height=760');
      }}
      if (!holeWindow) return;
      updateHolePopout(latestData);
      holeWindow.focus();
    }}

    function openPlayerModal(playerId) {{
      const player = latestRows.find((r) => String(r.id) === String(playerId));
      if (!player) return;

      document.getElementById('modal-title').textContent = player.name;
      document.getElementById('modal-subtitle').textContent = `Round ${{player.round}} | Status: ${{player.round_status}} | Today: ${{player.today}}`;

      const grid = document.getElementById('hole-grid');
      grid.innerHTML = (player.holes || []).map((h) => {{
        let cls = 'at-par';
        let stateText = 'AT PAR';
        const score = h.score;
        const par = h.par;
        if (typeof score === 'number' && typeof par === 'number') {{
          if (score < par) {{
            cls = 'under-par';
            stateText = 'BELOW PAR';
          }} else if (score > par) {{
            cls = 'over-par';
            stateText = 'ABOVE PAR';
          }}
        }}

        return `
          <div class="hole-box ${{cls}}">
            <div class="hole-num">HOLE ${{esc(h.hole)}}</div>
            <div class="hole-score">${{esc(score ?? '-')}}</div>
            <div class="hole-par">Par ${{esc(par ?? '-')}}</div>
            <div class="hole-state">${{stateText}}</div>
          </div>
        `;
      }}).join('');

      document.getElementById('player-modal').style.display = 'flex';
    }}

    function closePlayerModal() {{
      document.getElementById('player-modal').style.display = 'none';
    }}

    async function refresh() {{
      const meta = document.getElementById('meta');
      const error = document.getElementById('error');
      try {{
        const res = await fetch('/api/leaderboard', {{ cache: 'no-store' }});
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        latestData = data;
        renderTopThreePanel(data);
        renderRows(data);
        renderHoleAverages(data);
        updateHolePopout(data);
        meta.textContent = `Updated (feed): ${{data.updated}} | Round: ${{data.current_round}} | Local: ${{new Date().toLocaleString()}} | Refresh: 60s`;
        error.style.display = 'none';
        error.textContent = '';
      }} catch (e) {{
        error.style.display = 'block';
        error.textContent = 'Unable to fetch leaderboard. Retrying in 60 seconds.';
      }}
    }}

    document.getElementById('rows').addEventListener('click', (event) => {{
      const row = event.target.closest('tr[data-player-id]');
      if (!row) return;
      openPlayerModal(row.getAttribute('data-player-id'));
    }});

    document.getElementById('filter-all').addEventListener('click', () => {{
      filterMode = 'all';
      if (latestData) renderRows(latestData);
    }});

    document.getElementById('filter-best').addEventListener('click', () => {{
      filterMode = 'best';
      if (latestData) renderRows(latestData);
    }});

    document.getElementById('filter-worst').addEventListener('click', () => {{
      filterMode = 'worst';
      if (latestData) renderRows(latestData);
    }});

    document.getElementById('hole-filter-all').addEventListener('click', () => {{
      holeFilterMode = 'all';
      if (latestData) renderHoleAverages(latestData);
    }});

    document.getElementById('hole-filter-best').addEventListener('click', () => {{
      holeFilterMode = 'best';
      if (latestData) renderHoleAverages(latestData);
    }});

    document.getElementById('hole-filter-worst').addEventListener('click', () => {{
      holeFilterMode = 'worst';
      if (latestData) renderHoleAverages(latestData);
    }});

    document.querySelectorAll('.sort-btn').forEach((btn) => {{
      btn.addEventListener('click', () => {{
        const table = btn.getAttribute('data-table');
        const key = btn.getAttribute('data-key');

        if (table === 'players') {{
          if (playerSort.key === key) {{
            playerSort.dir = playerSort.dir === 'asc' ? 'desc' : 'asc';
          }} else {{
            playerSort = {{ key, dir: 'asc' }};
          }}
          if (latestData) renderRows(latestData);
          return;
        }}

        if (table === 'holes') {{
          if (holeSort.key === key) {{
            holeSort.dir = holeSort.dir === 'asc' ? 'desc' : 'asc';
          }} else {{
            holeSort = {{ key, dir: 'asc' }};
          }}
          if (latestData) renderHoleAverages(latestData);
        }}
      }});
    }});

    document.getElementById('close-modal').addEventListener('click', closePlayerModal);
    document.getElementById('popout-btn').addEventListener('click', async () => {{
      try {{
        const res = await fetch('/api/leaderboard', {{ cache: 'no-store' }});
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        openHolePopout(data);
      }} catch (e) {{
        const error = document.getElementById('error');
        error.style.display = 'block';
        error.textContent = 'Unable to open hole average pop-out because data refresh failed.';
      }}
    }});
    document.getElementById('player-modal').addEventListener('click', (event) => {{
      if (event.target.id === 'player-modal') closePlayerModal();
    }});
    document.addEventListener('keydown', (event) => {{
      if (event.key === 'Escape') closePlayerModal();
    }});

    refresh();
    setInterval(refresh, refreshMs);
  </script>
</body>
</html>
"""


def build_api_payload(url: str, timeout: int, top_n: int) -> dict[str, Any]:
    payload = fetch_scores(url, timeout=timeout)
    return extract_rows(payload, top_n=top_n)


class LeaderboardHandler(BaseHTTPRequestHandler):
    scores_url: str = SCORES_URL
    timeout: int = 10
    top_n: int = 30

    def _send_json(self, status_code: int, data: dict[str, Any]) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status_code: int, html_text: str) -> None:
        body = html_text.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send_html(200, render_index_html(self.top_n))
            return

        if self.path == "/api/leaderboard":
            try:
                data = build_api_payload(self.scores_url, self.timeout, self.top_n)
                self._send_json(200, data)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                self._send_json(
                    502,
                    {
                        "error": f"Unable to fetch feed: {exc}",
                        "local_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
            return

        msg = html.escape(f"Not Found: {self.path}")
        self._send_html(404, f"<h1>404</h1><p>{msg}</p>")

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def try_create_server(
    host: str,
    requested_port: int,
    handler_type: type[BaseHTTPRequestHandler],
    max_port_tries: int = 25,
) -> tuple[ThreadingHTTPServer, int, bool]:
    try:
        return ThreadingHTTPServer((host, requested_port), handler_type), requested_port, False
    except OSError as exc:
        if exc.errno not in (98, 10048):
            raise

    for candidate in range(requested_port + 1, requested_port + 1 + max_port_tries):
        try:
            return ThreadingHTTPServer((host, candidate), handler_type), candidate, True
        except OSError as exc:
            if exc.errno not in (98, 10048):
                raise

    raise OSError(
        f"Port {requested_port} is in use and no free port was found in the next {max_port_tries} ports."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a web page for the live Masters leaderboard.")
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host/interface to bind (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to serve on (default: 8000).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=30,
        help="How many leaderboard rows to show (default: 30).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="HTTP timeout in seconds (default: 10).",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=SCORES_URL,
        help="Override feed URL.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.port < 1 or args.port > 65535:
        print("Port must be between 1 and 65535.", file=sys.stderr)
        return 2
    if args.top < 1:
        print("Top must be 1 or higher.", file=sys.stderr)
        return 2

    handler_type = type(
        "ConfiguredLeaderboardHandler",
        (LeaderboardHandler,),
        {"scores_url": args.url, "timeout": args.timeout, "top_n": args.top},
    )

    try:
        server, actual_port, used_fallback = try_create_server(args.host, args.port, handler_type)
    except OSError as exc:
        print(f"Unable to start server: {exc}", file=sys.stderr)
        return 1

    if used_fallback:
        print(f"Port {args.port} was in use. Using port {actual_port} instead.")
    print(f"Serving Masters leaderboard at http://{args.host}:{actual_port}")
    print("The web page auto-refreshes every 60 seconds.")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
