#!/usr/bin/env python3

import re
import sys
import time
import datetime
import json
import random
import os
import unicodedata
from pathlib import Path
from collections import defaultdict, Counter
import html

# Regex patterns for log formats
LOG_LINE_RE_OLD = re.compile(r"^\[(?P<timestamp>[\d:-]+\s[\d:]+)\]\s+<(?P<nick>[^>]+)>\s(?P<msg>.*)$")
LOG_LINE_RE_NEW = re.compile(r"^\[(?P<timestamp>\d{2}:\d{2}:\d{2})\]\s+<(?P<nick>[^>]+)>\s(?P<msg>.*)$")
TOPIC_SET_RE = re.compile(
    r"^\[(?P<timestamp>[\d:-]+\s[\d:]+)\]\s\*\s(?P<setter>\S+)\sset the topic to\s\[(?P<topic>.+)\]$"
)
URL_RE = re.compile(r"(https?://\S+)")
SMILEY_RE = re.compile(r"[:;][\-^]?[\)D\(Pp]")

BRIDGE_NICKS = {
    n.strip().lower()
    for n in os.environ.get("BRIDGENICKS", "").split(",")
    if n.strip()
}
BRIDGE_MSG_RE = re.compile(r"^(?:\d*)?<@?([^>]+)>\s+(.+)$")

CACHE_DIR = Path(".cache_ircstats")


def clean_bridge_nick(nick):
    nick = "".join(
        ch for ch in nick if unicodedata.category(ch) != "Cf"
    )
    nick = re.sub(r"\s+", "_", nick)
    nick = re.sub(r"[^a-zA-Z0-9_\-\[\]\\\^\{\}`|]+", "", nick)
    return nick


def handle_bridge(nick, msg):
    if nick in BRIDGE_NICKS:
        m = BRIDGE_MSG_RE.match(msg)
        if not m:
            return None, None
        real_nick = clean_bridge_nick(m.group(1))
        real_msg = m.group(2)
        return real_nick.lower(), real_msg
    return nick, msg


def parse_line(line, current_date=None):
    line = line.rstrip("\n")
    m = LOG_LINE_RE_OLD.match(line)
    if m:
        dt_str = m.group("timestamp")
        try:
            dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None, None, None
        nick = m.group("nick").lower()
        msg = m.group("msg")
        return dt, nick, msg

    # fallback for new style logs (no date, only time)
    m = LOG_LINE_RE_NEW.match(line)
    if m and current_date:
        time_str = m.group("timestamp")
        try:
            dt_time = datetime.datetime.strptime(time_str, "%H:%M:%S").time()
            dt = datetime.datetime.combine(current_date, dt_time)
        except ValueError:
            return None, None, None
        nick = m.group("nick").lower()
        msg = m.group("msg")
        return dt, nick, msg

    # Topic line example
    m = TOPIC_SET_RE.match(line)
    if m:
        dt_str = m.group("timestamp")
        try:
            dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None, None, None
        setter = m.group("setter").lower()
        topic = m.group("topic")
        return dt, setter, topic  # special case for topic
    return None, None, None


def relative_day_string(dt):
    today = datetime.date.today()
    dt_date = dt.date()
    diff = (today - dt_date).days
    if diff == 0:
        return "today"
    elif diff == 1:
        return "yesterday"
    elif diff < 7:
        return f"{diff} days ago"
    else:
        return dt.strftime("%Y-%m-%d")
def build_known_nicks(log_dir, cache_file="known_nicks.json"):
    cache_path = Path(cache_file)
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            known = set(json.load(f))
        print(f"Loaded {len(known)} known nicks from cache.")
        return known

    known = set()
    path = Path(log_dir)
    for log_file in path.rglob("*.log"):
        try:
            date_part = datetime.datetime.strptime(log_file.stem, "%Y-%m-%d").date()
        except Exception:
            continue
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                # parse_line should return (datetime, nick, message)
                dt, nick, msg = parse_line(line, date_part)
                if not nick:
                    continue
                nick, msg = handle_bridge(nick, msg)
                if not nick:
                    continue
                known.add(nick)

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(sorted(known), f, indent=2)
    print(f"Built known nicks list with {len(known)} entries and cached to {cache_path}")
    return known


# def build_known_nicks(log_dir):
#     known = set()
#     path = Path(log_dir)
#     for log_file in path.rglob("*.log"):
#         try:
#             date_part = datetime.datetime.strptime(log_file.stem, "%Y-%m-%d").date()
#         except Exception:
#             continue
#         with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
#             for line in f:
#                 dt, nick, msg = parse_line(line, date_part)
#                 if nick:
#                     known.add(nick)
#     return known


def parse_log_file_with_nicks(log_file, known_nicks):
    # Data structures
    last_seen_by_user = {}
    messages_by_user = defaultdict(list)
    lines_by_user = Counter()
    words_by_user = Counter()
    mentions_by_user = defaultdict(Counter)
    url_counts = Counter()
    topics = []
    hours_active = Counter()
    dow_active = Counter()
    user_hour_active = defaultdict(Counter)
    word_counts = Counter()
    smiley_counts = Counter()
    total_lines = 0

    # Determine current_date for partial timestamp logs
    try:
        current_date = datetime.datetime.strptime(log_file.stem, "%Y-%m-%d").date()
    except Exception:
        current_date = None

    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            dt, nick, msg = parse_line(line, current_date)
            if dt is None:
                # check for topic set (special)
                m = TOPIC_SET_RE.match(line.rstrip("\n"))
                if m:
                    try:
                        dt = datetime.datetime.strptime(m.group("timestamp"), "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        continue
                    setter = m.group("setter").lower()
                    topic = m.group("topic")
                    topics.append({"time": dt.strftime("%Y-%m-%d %H:%M:%S"), "setter": setter, "topic": topic})
                continue
            if not nick:
                continue
            nick, msg = handle_bridge(nick, msg)
            if not nick:
                continue

            total_lines += 1
            lines_by_user[nick] += 1
            words_by_user[nick] += len(msg.split())

            if nick not in last_seen_by_user or dt > last_seen_by_user[nick]:
                last_seen_by_user[nick] = dt

            # Store last 50 messages for random quotes
            if len(messages_by_user[nick]) >= 50:
                messages_by_user[nick].pop(0)
            messages_by_user[nick].append(msg)

            # Extract mentions and word usage
            for word in msg.split():
                wclean = word.lower().strip(",.:;!?()[]{}<>\"'")
                if wclean in known_nicks and wclean != nick:
                    mentions_by_user[nick][wclean] += 1
                if wclean and wclean.isalpha():
                    word_counts[wclean] += 1

            # Extract URLs
            for url in URL_RE.findall(msg):
                url_counts[url] += 1

            # Smiley counts
            for sm in SMILEY_RE.findall(msg):
                smiley_counts[sm] += 1

            hours_active[dt.hour] += 1
            dow_active[dt.weekday()] += 1
            user_hour_active[nick][dt.hour] += 1

    return {
        "lines_by_user": lines_by_user,
        "words_by_user": words_by_user,
        "mentions_by_user": mentions_by_user,
        "url_counts": url_counts,
        "topics": topics,
        "hours_active": hours_active,
        "dow_active": dow_active,
        "word_counts": word_counts,
        "smiley_counts": smiley_counts,
        "total_lines": total_lines,
        "last_seen": last_seen_by_user,
        "messages": messages_by_user,
        "user_hour_active": user_hour_active,
    }


def merge_stats(global_stats, file_stats):
    for k in [
        "lines_by_user",
        "words_by_user",
        "url_counts",
        "hours_active",
        "dow_active",
        "word_counts",
        "smiley_counts",
    ]:
        if k in file_stats:
            global_stats[k].update(file_stats[k])
    # merge per-user hourly activity
    for user, hours in file_stats.get("user_hour_active", {}).items():
        global_stats["user_hour_active"][user].update(hours)
    # merge mentions
    for user, mentions in file_stats["mentions_by_user"].items():
        global_stats["mentions_by_user"][user].update(mentions)
    global_stats["topics"].extend(file_stats["topics"])
    global_stats["total_lines"] += file_stats["total_lines"]

    # merge last_seen with max timestamp
    for nick, dt in file_stats["last_seen"].items():
        if nick not in global_stats["last_seen"] or dt > global_stats["last_seen"][nick]:
            global_stats["last_seen"][nick] = dt

    # merge messages (keep last 50)
    for nick, msgs in file_stats["messages"].items():
        combined = global_stats["messages"][nick] + msgs
        global_stats["messages"][nick] = combined[-50:]


def save_cache(log_file, data):
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path = CACHE_DIR / (log_file.stem + ".json")

    def serialize_value(val):
        if isinstance(val, datetime.datetime):
            return val.isoformat()
        return val

    serialized = {}
    for k, v in data.items():
        if isinstance(v, dict) or isinstance(v, Counter) or isinstance(v, defaultdict):
            # serialize all datetime values inside nested dicts
            serialized[k] = {user: serialize_value(val) for user, val in v.items()}
        else:
            serialized[k] = v

    # topics is list of dicts - no datetime objects left, but just to be sure:
    serialized["topics"] = data["topics"]
    serialized["total_lines"] = data["total_lines"]

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(serialized, f, indent=1)


def load_cache(log_file):
    cache_path = CACHE_DIR / (log_file.stem + ".json")
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Deserialize last_seen timestamps
        raw["last_seen"] = {k: datetime.datetime.fromisoformat(v) for k, v in raw.get("last_seen", {}).items()}
        # Convert per-user hour maps back to Counters
        raw["user_hour_active"] = {
            user: Counter({int(h): c for h, c in hours.items()})
            for user, hours in raw.get("user_hour_active", {}).items()
        }
        # Ensure hourly and weekday activity use integer keys
        raw["hours_active"] = Counter({int(h): c for h, c in raw.get("hours_active", {}).items()})
        raw["dow_active"] = Counter({int(d): c for d, c in raw.get("dow_active", {}).items()})
        return raw
    except Exception:
        return None


def write_detailed_nick_stats(global_stats, output):
    # Sort by lines desc
    sorted_users = sorted(global_stats["lines_by_user"].items(), key=lambda x: x[1], reverse=True)[:20]

    output.append("<h2>Detailed Nick Stats</h2>")
    output.append("<table>")
    output.append("<tr><th>Nick</th><th>Number of lines</th><th>When?</th><th>Last seen</th><th>Random quote</th></tr>")

    for nick, lines in sorted_users:
        last_seen = global_stats["last_seen"].get(nick)
        if last_seen:
            when_str = relative_day_string(last_seen)
            last_seen_str = last_seen.strftime("%Y-%m-%d %H:%M:%S")
        else:
            when_str = "unknown"
            last_seen_str = "unknown"

        quotes = global_stats["messages"].get(nick, [])
        quote = random.choice(quotes) if quotes else ""

        quote_escaped = html.escape(quote)
        nick_escaped = html.escape(nick)

        output.append(
            f'<tr><td>{nick_escaped}</td><td>{lines}</td><td>{when_str}</td><td>{last_seen_str}</td><td>"{quote_escaped}"</td></tr>'
        )

    output.append("</table>")


def write_html_report(global_stats, output_path):
    def build_rows(items, col1_title, col2_title):
        rows = [f"<tr><th>{col1_title}</th><th>{col2_title}</th></tr>"]
        for k, v in items:
            rows.append(f"<tr><td>{html.escape(str(k))}</td><td>{v}</td></tr>")
        return "\n".join(rows)

    def hour_to_color(hour):
        if 0 <= hour < 6:
            return "#1e88e5"  # blue
        if 6 <= hour < 12:
            return "#e53935"  # red
        if 12 <= hour < 18:
            return "#fdd835"  # yellow
        return "#43a047"  # green

    output = []

    output.append("<!DOCTYPE html>")
    output.append("<html lang='en'>")
    output.append(
        "<head><meta charset='UTF-8' /><meta name='viewport' content='width=device-width, initial-scale=1' />"
    )
    output.append("<title>IRC Stats Report</title>")
    output.append(
        """
    <style>
    body { font-family: Verdana, Arial, sans-serif; margin: 0; background: #f5f5f5; color: #333; }
    header { background: linear-gradient(90deg, #263238, #37474f); color: #fff; padding: 20px 0; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }
    header h1 { margin: 0; font-size: 2rem; }
    main { max-width: 1000px; margin: 30px auto; padding: 0 15px; }
    section { margin-bottom: 40px; }
    h2 { border-bottom: 2px solid #ccc; padding-bottom: 4px; color: #263238; }
    table { border-collapse: collapse; width: 100%; background: #fff; margin-top: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
    th { background: #263238; color: #fff; }
    tr:nth-child(even) { background-color: #f0f8ff; }
    tr:hover { background-color: #e1f5fe; }
    ul { background: #fff; padding: 15px; border: 1px solid #ddd; }
    </style>
    """
    )
    output.append("</head><body>")

    channel = os.environ.get("CHANNEL_NAME", "#channel")
    network = os.environ.get("NETWORK_NAME", "IRC")
    author = os.environ.get("AUTHOR_NAME", "Rusty")
    generated_on = datetime.datetime.now().strftime("%A %d %B %Y - %H:%M:%S")

    log_dates = global_stats.get("log_dates", set())
    reporting_days = (
        (max(log_dates) - min(log_dates)).days + 1 if log_dates else 0
    )
    active_nicks = len(global_stats["lines_by_user"])

    header_lines = [
        f"<h1>{html.escape(channel)} @ {html.escape(network)} stats by {html.escape(author)}</h1>",
        f"<p>Statistics generated on {generated_on}</p>",
    ]
    if reporting_days and active_nicks:
        header_lines.append(
            f"<p>During this {reporting_days}-day reporting period, a total of {active_nicks} different nicks were represented on {html.escape(channel)}.</p>"
        )
    output.append("<header>" + "".join(header_lines) + "</header>")
    output.append("<main>")

    total_lines = global_stats["total_lines"]
    active_nicks = len(global_stats["lines_by_user"])
    log_dates = global_stats.get("log_dates", set())
    num_days = len(log_dates)
    first_day = min(log_dates).strftime("%Y-%m-%d") if log_dates else ""
    last_day = max(log_dates).strftime("%Y-%m-%d") if log_dates else ""
    avg_per_day = total_lines / num_days if num_days else 0
    most_active_day = ""
    most_active_count = 0
    if global_stats["dow_active"]:
        idx, most_active_count = max(
            global_stats["dow_active"].items(), key=lambda x: x[1]
        )
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        most_active_day = days[int(idx)]

    output.append("<section id='summary'>")
    output.append("<h2>Summary</h2>")
    output.append("<ul>")
    output.append(f"<li>Total lines: {total_lines}</li>")
    if num_days:
        output.append(
            f"<li>From {first_day} to {last_day} ({num_days} days)</li>"
        )
        output.append(
            f"<li>Average lines per day: {avg_per_day:.2f}</li>"
        )
    output.append(f"<li>Active nicks: {active_nicks}</li>")
    if most_active_day:
        output.append(
            f"<li>Most active day: {most_active_day} ({most_active_count} lines)</li>"
        )
    output.append("</ul>")
    output.append("</section>")

    # Most Active Nicks
    output.append("<section id='most-active-nicks'>")
    output.append("<h2>Most Active Nicks</h2>")
    top_talkers = global_stats["lines_by_user"].most_common(10)
    max_lines = top_talkers[0][1] if top_talkers else 0
    output.append("<table>")
    output.append(
        "<tr><th>Nick</th><th>Lines</th><th>Words</th><th>Last seen</th><th>When?</th></tr>"
    )
    for nick, lines in top_talkers:
        width = (lines / max_lines * 100) if max_lines else 0
        hours = global_stats["user_hour_active"].get(nick, {})
        peak_hour = max(hours, key=hours.get) if hours else 0
        color = hour_to_color(peak_hour)
        line_bar = f"<div style='background:{color};height:10px;width:{width}%;'></div>"
        words = global_stats["words_by_user"].get(nick, 0)
        last_seen_dt = global_stats["last_seen"].get(nick)
        last_seen_str = relative_day_string(last_seen_dt) if last_seen_dt else "unknown"
        max_hour_count = max(hours.values()) if hours else 0
        segments = []
        for h in range(24):
            cnt = hours.get(h, 0)
            h_height = (cnt / max_hour_count * 10) if max_hour_count else 0
            seg_color = hour_to_color(h)
            segments.append(
                f"<div style='display:inline-block;width:4px;height:{h_height}px;background:{seg_color}'></div>"
            )
        when_bar = f"<div style='height:10px'>{''.join(segments)}</div>"
        output.append(
            f"<tr><td>{html.escape(nick)}</td><td>{lines}{line_bar}</td><td>{words}</td><td>{last_seen_str}</td><td>{when_bar}</td></tr>"
        )
    output.append("</table>")
    output.append("</section>")

    # Most used words
    output.append("<section id='top-words'>")
    output.append("<h2>Most Used Words</h2>")
    output.append("<table>")
    output.append(build_rows(global_stats["word_counts"].most_common(10), "Word", "Count"))
    output.append("</table>")
    output.append("</section>")

    # Most mentioned (aggregate all mentions)
    aggregate_mentions = Counter()
    for user, mentions in global_stats["mentions_by_user"].items():
        for nick, cnt in mentions.items():
            if nick in global_stats["lines_by_user"]:
                aggregate_mentions[nick] += cnt

    output.append("<section id='most-mentioned'>")
    output.append("<h2>Most Mentioned (by all users)</h2>")
    output.append("<table>")
    output.append(build_rows(aggregate_mentions.most_common(10), "Nick", "Mentions"))
    output.append("</table>")
    output.append("</section>")

    # Most referenced URLs
    output.append("<section id='top-urls'>")
    output.append("<h2>Most Referenced URLs</h2>")
    output.append("<table>")
    top_urls = [
        (url, c)
        for url, c in global_stats["url_counts"].most_common()
        if c >= 2
    ][:10]
    output.append(build_rows(top_urls, "URL", "Count"))
    output.append("</table>")
    output.append("</section>")

    # Smiley stats
    output.append("<section id='smiley-stats'>")
    output.append("<h2>Smileys</h2>")
    output.append("<table>")
    output.append(build_rows(global_stats["smiley_counts"].most_common(10), "Smiley", "Count"))
    output.append("</table>")
    output.append("</section>")

    # Latest topics
    output.append("<section id='latest-topics'>")
    output.append("<h2>Latest Topics</h2>")
    output.append("<ul>")
    latest_topics = sorted(global_stats["topics"], key=lambda x: x["time"], reverse=True)[:5]
    for topic in latest_topics:
        output.append(
            f"<li><strong>{html.escape(topic['time'])}</strong> by <em>{html.escape(topic['setter'])}</em>: {html.escape(topic['topic'])}</li>"
        )
    output.append("</ul>")
    output.append("</section>")

    # Activity by hour
    output.append("<section id='activity-by-hour'>")
    output.append("<h2>Most Active Times</h2>")
    output.append("<table><tr><th>Hour</th><th>Messages</th><th></th></tr>")
    max_hour = (
        max(global_stats["hours_active"].values())
        if global_stats["hours_active"]
        else 0
    )
    for hour in range(24):
        count = global_stats["hours_active"].get(hour, 0)
        width = (count / max_hour * 100) if max_hour else 0
        color = hour_to_color(hour)
        output.append(
            f"<tr><td>{hour:02d}:00</td><td>{count}</td><td><div style='background:{color};height:10px;width:{width}%;'></div></td></tr>"
        )
    output.append("</table>")
    output.append("</section>")

    # Activity by day
    output.append("<section id='activity-by-day'>")
    output.append("<h2>Activity by Day</h2>")
    output.append("<table><tr><th>Day</th><th>Messages</th></tr>")
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for i, day in enumerate(days):
        count = global_stats["dow_active"].get(i, 0)
        output.append(f"<tr><td>{day}</td><td>{count}</td></tr>")
    output.append("</table>")
    output.append("</section>")

    # Detailed nick stats table
    output.append("<section id='nick-details'>")
    write_detailed_nick_stats(global_stats, output)
    output.append("</section>")

    output.append("</main></body></html>")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"Wrote HTML report to {output_path}")


def main(log_dir):
    path = Path(log_dir)
    today = datetime.date.today()

    print(f"Building known nick list from logs in {log_dir}...")
    known_nicks = build_known_nicks(log_dir)
    print(f"Known nicks found: {len(known_nicks)}")

    global_stats = {
        "lines_by_user": Counter(),
        "words_by_user": Counter(),
        "mentions_by_user": defaultdict(Counter),
        "url_counts": Counter(),
        "topics": [],
        "hours_active": Counter(),
        "dow_active": Counter(),
        "word_counts": Counter(),
        "smiley_counts": Counter(),
        "total_lines": 0,
        "last_seen": {},
        "messages": defaultdict(list),
        "log_dates": set(),
        "user_hour_active": defaultdict(Counter),
    }

    total_start = time.perf_counter()

    for log_file in sorted(path.rglob("*.log")):
        try:
            file_date = datetime.datetime.strptime(log_file.stem, "%Y-%m-%d").date()
        except Exception:
            continue
        global_stats["log_dates"].add(file_date)

        age_days = (today - file_date).days

        start = time.perf_counter()

        cache_data = None
        if file_date < today:
            cache_data = load_cache(log_file)

        if cache_data:
            merge_stats(global_stats, cache_data)
            elapsed = time.perf_counter() - start
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            time_str = f"{int(h):02d}:{int(m):02d}:{int(s):02d}"
            print(
                f"pisg Analyzing log {log_file}... cached, {age_days} days, {global_stats['total_lines']} lines total (took {time_str})"
            )
        else:
            file_stats = parse_log_file_with_nicks(log_file, known_nicks)
            merge_stats(global_stats, file_stats)
            save_cache(log_file, file_stats)
            elapsed = time.perf_counter() - start
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            time_str = f"{int(h):02d}:{int(m):02d}:{int(s):02d}"
            if file_date == today:
                print(
                    f"pisg Analyzing log {log_file}... parsed fresh, {global_stats['total_lines']} lines total (took {time_str})"
                )
            else:
                print(
                    f"pisg Analyzing log {log_file}... parsed and cached (old file), {global_stats['total_lines']} lines total (took {time_str})"
                )

    total_elapsed = time.perf_counter() - total_start
    h, rem = divmod(total_elapsed, 3600)
    m, s = divmod(rem, 60)
    print(
        f"pisg Channel analyzed successfully in {int(h):02d} hours, {int(m):02d} minutes and {int(s):02d} seconds on {datetime.datetime.now().strftime('%a %b %d %H:%M:%S %Y')}"
    )

    # Write HTML report
    write_html_report(global_stats, path / "index.html")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} /path/to/logdir")
        sys.exit(1)
    main(sys.argv[1])
