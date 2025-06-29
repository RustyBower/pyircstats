#!/usr/bin/env python3

import re
import sys
import time
import datetime
import json
import random
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

CACHE_DIR = Path(".cache_ircstats")

BLACKLIST = {"like", "shit", "the", "a", "you", "and", "to", "for", "of", "in", "on", "is", "it", "i", "we", "me", "my"}


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


def is_valid_nick(nick):
    return nick.lower() not in BLACKLIST


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
                if nick and is_valid_nick(nick):
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

            total_lines += 1
            lines_by_user[nick] += 1
            words_by_user[nick] += len(msg.split())

            if nick not in last_seen_by_user or dt > last_seen_by_user[nick]:
                last_seen_by_user[nick] = dt

            # Store last 50 messages for random quotes
            if len(messages_by_user[nick]) >= 50:
                messages_by_user[nick].pop(0)
            messages_by_user[nick].append(msg)

            # Extract mentions (simple approach: word matches known nick)
            for word in msg.split():
                wclean = word.lower().strip(",.:;!?()[]{}<>\"'")
                if wclean in known_nicks and wclean != nick:
                    mentions_by_user[nick][wclean] += 1

            # Extract URLs
            for url in URL_RE.findall(msg):
                url_counts[url] += 1

            hours_active[dt.hour] += 1

    return {
        "lines_by_user": lines_by_user,
        "words_by_user": words_by_user,
        "mentions_by_user": mentions_by_user,
        "url_counts": url_counts,
        "topics": topics,
        "hours_active": hours_active,
        "total_lines": total_lines,
        "last_seen": last_seen_by_user,
        "messages": messages_by_user,
    }


def merge_stats(global_stats, file_stats):
    for k in ["lines_by_user", "words_by_user", "url_counts", "hours_active"]:
        global_stats[k].update(file_stats[k])
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
        # messages and others remain as is
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
    body { font-family: Arial, sans-serif; margin: 20px; background: #f8f9fa; color: #212529; }
    h1, h2 { border-bottom: 2px solid #343a40; padding-bottom: 6px; }
    table { border-collapse: collapse; width: 100%; max-width: 800px; margin-bottom: 30px; }
    th, td { border: 1px solid #dee2e6; padding: 8px 12px; text-align: left; }
    th { background-color: #343a40; color: white; }
    tr:nth-child(even) { background-color: #e9ecef; }
    ul { max-width: 800px; }
    </style>
    """
    )
    output.append("</head><body>")
    output.append("<h1>IRC Channel Statistics</h1>")

    # Top Talkers (lines)
    output.append("<h2>Top Talkers (Lines)</h2>")
    output.append("<table>")
    output.append(build_rows(global_stats["lines_by_user"].most_common(10), "Nick", "Lines"))
    output.append("</table>")

    # Wordiest users
    output.append("<h2>Wordiest Users</h2>")
    output.append("<table>")
    output.append(build_rows(global_stats["words_by_user"].most_common(10), "Nick", "Words"))
    output.append("</table>")

    # Most mentioned (aggregate all mentions)
    aggregate_mentions = Counter()
    for user, mentions in global_stats["mentions_by_user"].items():
        aggregate_mentions.update(mentions)

    output.append("<h2>Most Mentioned (by all users)</h2>")
    output.append("<table>")
    output.append(build_rows(aggregate_mentions.most_common(10), "Nick", "Mentions"))
    output.append("</table>")

    # Most referenced URLs
    output.append("<h2>Most Referenced URLs</h2>")
    output.append("<table>")
    output.append(build_rows(global_stats["url_counts"].most_common(10), "URL", "Count"))
    output.append("</table>")

    # Latest topics
    output.append("<h2>Latest Topics</h2>")
    output.append("<ul>")
    latest_topics = sorted(global_stats["topics"], key=lambda x: x["time"], reverse=True)[:5]
    for topic in latest_topics:
        output.append(
            f"<li><strong>{html.escape(topic['time'])}</strong> by <em>{html.escape(topic['setter'])}</em>: {html.escape(topic['topic'])}</li>"
        )
    output.append("</ul>")

    # Activity by hour
    output.append("<h2>Activity by Hour</h2>")
    output.append("<table><tr><th>Hour</th><th>Messages</th></tr>")
    for hour in range(24):
        count = global_stats["hours_active"].get(hour, 0)
        output.append(f"<tr><td>{hour:02d}:00</td><td>{count}</td></tr>")
    output.append("</table>")

    # Detailed nick stats table
    write_detailed_nick_stats(global_stats, output)

    output.append("</body></html>")

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
        "total_lines": 0,
        "last_seen": {},
        "messages": defaultdict(list),
    }

    total_start = time.perf_counter()

    for log_file in sorted(path.rglob("*.log")):
        try:
            file_date = datetime.datetime.strptime(log_file.stem, "%Y-%m-%d").date()
        except Exception:
            continue

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
