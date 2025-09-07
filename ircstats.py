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
LOG_ACTION_RE_OLD = re.compile(r"^\[(?P<timestamp>[\d:-]+\s[\d:]+)\]\s\*\s(?P<nick>\S+)\s(?P<msg>.*)$")
LOG_ACTION_RE_NEW = re.compile(r"^\[(?P<timestamp>\d{2}:\d{2}:\d{2})\]\s\*\s(?P<nick>\S+)\s(?P<msg>.*)$")
LOG_KICK_RE_OLD = re.compile(
    r"^\[(?P<timestamp>[\d:-]+\s[\d:]+)\]\s\*\*\*\s(?P<victim>\S+) was kicked by (?P<kicker>\S+)(?: \((?P<reason>.*)\))?$"
)
LOG_KICK_RE_NEW = re.compile(
    r"^\[(?P<timestamp>\d{2}:\d{2}:\d{2})\]\s\*\*\*\s(?P<victim>\S+) was kicked by (?P<kicker>\S+)(?: \((?P<reason>.*)\))?$"
)
LOG_JOIN_RE_OLD = re.compile(r"^\[(?P<timestamp>[\d:-]+\s[\d:]+)\]\s\*\*\*\s(?P<nick>\S+) has joined")
LOG_JOIN_RE_NEW = re.compile(r"^\[(?P<timestamp>\d{2}:\d{2}:\d{2})\]\s\*\*\*\s(?P<nick>\S+) has joined")
LOG_MODE_RE_OLD = re.compile(
    r"^\[(?P<timestamp>[\d:-]+\s[\d:]+)\]\s\*\*\*\s(?P<setter>\S+) sets mode (?P<mode>[+-]o) (?P<target>\S+)"
)
LOG_MODE_RE_NEW = re.compile(
    r"^\[(?P<timestamp>\d{2}:\d{2}:\d{2})\]\s\*\*\*\s(?P<setter>\S+) sets mode (?P<mode>[+-]o) (?P<target>\S+)"
)
TOPIC_SET_RE = re.compile(
    r"^\[(?P<timestamp>[\d:-]+\s[\d:]+)\]\s\*\s(?P<setter>\S+)\sset the topic to\s\[(?P<topic>.+)\]$"
)
URL_RE = re.compile(r"(https?://\S+)")
SMILEY_RE = re.compile(r"[:;][\-^]?[\)D\(Pp]")
BAD_WORDS = {"fuck", "shit", "damn", "bitch", "crap", "ass", "piss", "dick", "cunt"}

try:
    from profanity_check import predict as profanity_predict
except Exception:  # pragma: no cover - optional dependency
    profanity_predict = None

_PROFANITY_CACHE = {}


def is_profane(word: str) -> bool:
    word = word.lower()
    if profanity_predict:
        if word not in _PROFANITY_CACHE:
            _PROFANITY_CACHE[word] = bool(profanity_predict([word])[0])
        return _PROFANITY_CACHE[word]
    return word in BAD_WORDS

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


def hour_to_color(hour):
    if 0 <= hour < 6:
        return "#1e88e5"  # blue
    if 6 <= hour < 12:
        return "#e53935"  # red
    if 12 <= hour < 18:
        return "#fdd835"  # yellow
    return "#43a047"  # green
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
    word_last_used = {}
    mention_last_by = {}
    kicks_received = Counter()
    kicks_given = Counter()
    kick_examples = {}
    joins = Counter()
    actions = Counter()
    action_examples = {}
    op_give_count = 0
    op_take_count = 0
    monologues = Counter()
    bad_word_counts = Counter()
    total_lines = 0
    last_nick = None
    streak = 0

    # Determine current_date for partial timestamp logs
    try:
        current_date = datetime.datetime.strptime(log_file.stem, "%Y-%m-%d").date()
    except Exception:
        current_date = None

    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")

            m = LOG_KICK_RE_OLD.match(line) or LOG_KICK_RE_NEW.match(line)
            if m:
                dt_str = m.group("timestamp")
                try:
                    if len(dt_str) == 8:
                        dt_time = datetime.datetime.strptime(dt_str, "%H:%M:%S").time()
                        dt = datetime.datetime.combine(current_date, dt_time) if current_date else None
                    else:
                        dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    dt = None
                victim = m.group("victim").lower()
                kicker = m.group("kicker").lower()
                kicks_received[victim] += 1
                kicks_given[kicker] += 1
                if victim not in kick_examples:
                    kick_examples[victim] = line.split("] ", 1)[1]
                continue

            m = LOG_JOIN_RE_OLD.match(line) or LOG_JOIN_RE_NEW.match(line)
            if m:
                nick = m.group("nick").lower()
                joins[nick] += 1
                continue

            m = LOG_MODE_RE_OLD.match(line) or LOG_MODE_RE_NEW.match(line)
            if m:
                mode = m.group("mode")
                if mode == "+o":
                    op_give_count += 1
                elif mode == "-o":
                    op_take_count += 1
                continue

            m = LOG_ACTION_RE_OLD.match(line) or LOG_ACTION_RE_NEW.match(line)
            if m:
                dt_str = m.group("timestamp")
                try:
                    if len(dt_str) == 8:
                        dt_time = datetime.datetime.strptime(dt_str, "%H:%M:%S").time()
                        dt = datetime.datetime.combine(current_date, dt_time) if current_date else None
                    else:
                        dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    dt = None
                nick = m.group("nick").lower()
                msg = m.group("msg")
                is_action = True
            else:
                dt, nick, msg = parse_line(line, current_date)
                is_action = False
            if dt is None or not nick:
                # check for topic set (special)
                m = TOPIC_SET_RE.match(line)
                if m:
                    try:
                        dt = datetime.datetime.strptime(m.group("timestamp"), "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        continue
                    setter = m.group("setter").lower()
                    topic = m.group("topic")
                    topics.append({"time": dt.strftime("%Y-%m-%d %H:%M:%S"), "setter": setter, "topic": topic})
                continue

            nick, msg = handle_bridge(nick, msg)
            if not nick:
                continue

            total_lines += 1
            lines_by_user[nick] += 1
            words = msg.split()
            words_by_user[nick] += len(words)

            if nick not in last_seen_by_user or dt > last_seen_by_user[nick]:
                last_seen_by_user[nick] = dt

            if len(messages_by_user[nick]) >= 50:
                messages_by_user[nick].pop(0)
            messages_by_user[nick].append(msg)

            for word in words:
                wclean = word.lower().strip(",.:;!?()[]{}<>\"'")
                if wclean in known_nicks and wclean != nick:
                    mentions_by_user[nick][wclean] += 1
                    mention_last_by[wclean] = (dt, nick)
                if wclean and wclean.isalpha():
                    word_counts[wclean] += 1
                    word_last_used[wclean] = (dt, nick)
                if is_profane(wclean):
                    bad_word_counts[nick] += 1

            for url in URL_RE.findall(msg):
                url_counts[url] += 1

            for sm in SMILEY_RE.findall(msg):
                smiley_counts[sm] += 1

            hours_active[dt.hour] += 1
            dow_active[dt.weekday()] += 1
            user_hour_active[nick][dt.hour] += 1

            if is_action:
                op_line = False
                if "set +o" in msg or "sets mode +o" in msg:
                    op_give_count += 1
                    op_line = True
                elif "set -o" in msg or "sets mode -o" in msg:
                    op_take_count += 1
                    op_line = True

                if not op_line:
                    actions[nick] += 1
                    if nick not in action_examples:
                        action_examples[nick] = f"* {nick} {msg}"

            if nick == last_nick:
                streak += 1
                if streak == 6:
                    monologues[nick] += 1
            else:
                last_nick = nick
                streak = 1

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
        "word_last_used": word_last_used,
        "mention_last_by": mention_last_by,
        "kicks_received": kicks_received,
        "kicks_given": kicks_given,
        "kick_examples": kick_examples,
        "joins": joins,
        "actions": actions,
        "action_examples": action_examples,
        "op_give_count": op_give_count,
        "op_take_count": op_take_count,
        "monologues": monologues,
        "bad_word_counts": bad_word_counts,
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

    # merge word last used info
    for word, (dt, nick) in file_stats.get("word_last_used", {}).items():
        prev = global_stats["word_last_used"].get(word)
        if not prev or dt > prev[0]:
            global_stats["word_last_used"][word] = (dt, nick)

    # merge mention last by info
    for word, (dt, nick) in file_stats.get("mention_last_by", {}).items():
        prev = global_stats["mention_last_by"].get(word)
        if not prev or dt > prev[0]:
            global_stats["mention_last_by"][word] = (dt, nick)

    for k in [
        "kicks_received",
        "kicks_given",
        "joins",
        "actions",
        "monologues",
        "bad_word_counts",
    ]:
        if k in file_stats:
            global_stats[k].update(file_stats[k])

    for nick, line in file_stats.get("kick_examples", {}).items():
        global_stats.setdefault("kick_examples", {})
        if nick not in global_stats["kick_examples"]:
            global_stats["kick_examples"][nick] = line

    for nick, line in file_stats.get("action_examples", {}).items():
        global_stats.setdefault("action_examples", {})
        if nick not in global_stats["action_examples"]:
            global_stats["action_examples"][nick] = line

    global_stats["op_give_count"] = global_stats.get("op_give_count", 0) + file_stats.get(
        "op_give_count", 0
    )
    global_stats["op_take_count"] = global_stats.get("op_take_count", 0) + file_stats.get(
        "op_take_count", 0
    )


def save_cache(log_file, data):
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path = CACHE_DIR / (log_file.stem + ".json")

    def serialize_value(val):
        if isinstance(val, datetime.datetime):
            return val.isoformat()
        return val

    serialized = {}
    for k, v in data.items():
        if k in ["word_last_used", "mention_last_by"]:
            serialized[k] = {
                word: {"time": val[0].isoformat(), "nick": val[1]}
                for word, val in v.items()
            }
        elif isinstance(v, dict) or isinstance(v, Counter) or isinstance(v, defaultdict):
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
        raw["word_last_used"] = {
            w: (datetime.datetime.fromisoformat(v["time"]), v["nick"])
            for w, v in raw.get("word_last_used", {}).items()
        }
        raw["mention_last_by"] = {
            w: (datetime.datetime.fromisoformat(v["time"]), v["nick"])
            for w, v in raw.get("mention_last_by", {}).items()
        }
        for k in [
            "kicks_received",
            "kicks_given",
            "joins",
            "actions",
            "monologues",
            "bad_word_counts",
        ]:
            raw[k] = Counter(raw.get(k, {}))
        raw["kick_examples"] = raw.get("kick_examples", {})
        raw["action_examples"] = raw.get("action_examples", {})
        raw["op_give_count"] = raw.get("op_give_count", 0)
        raw["op_take_count"] = raw.get("op_take_count", 0)
        return raw
    except Exception:
        return None


def write_most_active_nicks(global_stats, output):
    sorted_users = sorted(
        global_stats["lines_by_user"].items(), key=lambda x: x[1], reverse=True
    )[:10]

    output.append("<section id='most-active-nicks' style='max-width:800px;margin:auto'>")
    output.append("<h2>Most Active Nicks</h2>")
    output.append(
        "<table><tr><th>Nick</th><th>Number of lines</th><th>Activity</th><th>Last seen</th><th>Random quote</th></tr>"
    )

    for nick, lines in sorted_users:
        hours = global_stats["user_hour_active"].get(nick, {})
        total = sum(hours.values())
        segments = []
        if total:
            groups = [
                sum(hours.get(h, 0) for h in range(0, 6)),
                sum(hours.get(h, 0) for h in range(6, 12)),
                sum(hours.get(h, 0) for h in range(12, 18)),
                sum(hours.get(h, 0) for h in range(18, 24)),
            ]
            for idx, count in enumerate(groups):
                width = count / total * 100
                segments.append(
                    f"<div style='background:{hour_to_color(idx*6)};width:{width}%;height:10px'></div>"
                )
        activity_bar = (
            f"<div style='display:flex;width:100%;height:10px'>{''.join(segments)}</div>"
            if segments
            else "<div style='height:10px'></div>"
        )

        last_seen_dt = global_stats["last_seen"].get(nick)
        last_seen_str = (
            relative_day_string(last_seen_dt) if last_seen_dt else "unknown"
        )
        quotes = global_stats["messages"].get(nick, [])
        quote = random.choice(quotes) if quotes else ""

        output.append(
            f"<tr><td>{html.escape(nick)}</td><td>{lines}</td><td>{activity_bar}</td><td>{html.escape(last_seen_str)}</td><td class='quote'>\"{html.escape(quote)}\"</td></tr>"
        )

    output.append("</table></section>")


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
    td.quote { max-width: 300px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
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

    # Channel activity by hour
    max_hour = (
        max(global_stats["hours_active"].values())
        if global_stats["hours_active"]
        else 0
    )
    total_hour_lines = sum(global_stats["hours_active"].values())
    output.append("<section id='activity-by-hour'>")
    output.append("<h2>Most Active Times</h2>")
    output.append("<div style='display:flex;align-items:flex-end;height:120px'>")
    for hour in range(24):
        count = global_stats["hours_active"].get(hour, 0)
        height = (count / max_hour * 100) if max_hour else 0
        percent = (count / total_hour_lines * 100) if total_hour_lines else 0
        color = hour_to_color(hour)
        output.append(
            "<div style='flex:1;margin:0 1px;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center'>"
            f"<div style='font-size:smaller'>{percent:.1f}%</div>"
            f"<div style='background:{color};height:{height}%;width:100%'></div>"
            f"<div style='font-size:smaller'>{hour:02d}</div>"
            "</div>"
        )
    output.append("</div>")
    output.append(
        "<div style='display:flex;justify-content:space-between;font-size:smaller;margin-top:4px'>"
        "<span style='color:#1e88e5'>0-5</span>"
        "<span style='color:#e53935'>6-11</span>"
        "<span style='color:#fdd835'>12-17</span>"
        "<span style='color:#43a047'>18-23</span>"
        "</div>"
    )
    output.append("</section>")

    # Most Active Nicks table with stacked bars
    write_most_active_nicks(global_stats, output)

    # Most used words
    output.append("<section id='top-words'>")
    output.append("<h2>Most Used Words</h2>")
    output.append("<table><tr><th>Word</th><th>Count</th><th>Last used by</th></tr>")
    for word, cnt in global_stats["word_counts"].most_common(10):
        last_by = global_stats["word_last_used"].get(word, (None, "unknown"))[1]
        output.append(
            f"<tr><td>{html.escape(word)}</td><td>{cnt}</td><td>{html.escape(last_by)}</td></tr>"
        )
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
    output.append("<table><tr><th>Nick</th><th>Mentions</th><th>Last mentioned by</th></tr>")
    for nick, cnt in aggregate_mentions.most_common(10):
        last_by = global_stats["mention_last_by"].get(nick, (None, "unknown"))[1]
        output.append(
            f"<tr><td>{html.escape(nick)}</td><td>{cnt}</td><td>{html.escape(last_by)}</td></tr>"
        )
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
    output.append(
        build_rows(global_stats["smiley_counts"].most_common(10), "Smiley", "Count")
    )
    output.append("</table>")
    output.append("</section>")

    # Other interesting numbers
    write_other_numbers(global_stats, output, channel)

    # Latest topics
    if global_stats["topics"]:
        output.append("<section id='latest-topics'>")
        output.append("<h2>Latest Topics</h2>")
        output.append("<ul>")
        latest_topics = sorted(
            global_stats["topics"], key=lambda x: x["time"], reverse=True
        )[:5]
        for topic in latest_topics:
            output.append(
                f"<li><strong>{html.escape(topic['time'])}</strong> by <em>{html.escape(topic['setter'])}</em>: {html.escape(topic['topic'])}</li>"
            )
        output.append("</ul>")
        output.append("</section>")

    output.append("</main>")

    gen_time = global_stats.get("generation_time", 0)
    h, rem = divmod(gen_time, 3600)
    m, s = divmod(rem, 60)
    output.append(
        "<footer style='text-align:center;font-size:smaller;margin:20px 0;color:#666'>"
    )
    output.append(f"Total number of lines: {global_stats['total_lines']}.<br>")
    output.append("Stats generated by pyircstats.<br>")
    output.append(
        f"Stats generated in {int(h):02d} hours {int(m):02d} minutes and {int(s):02d} seconds"
    )
    output.append("</footer></body></html>")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"Wrote HTML report to {output_path}")


def write_other_numbers(global_stats, output, channel):
    stats = []
    kicks_received = global_stats.get("kicks_received", Counter())
    if kicks_received:
        victim1, count1 = kicks_received.most_common(1)[0]
        example = global_stats.get("kick_examples", {}).get(victim1)
        stats.append(
            (f"{victim1} wasn't very popular, getting kicked {count1} times!", example)
        )
        if len(kicks_received) > 1:
            victim2, count2 = kicks_received.most_common(2)[1]
            stats.append(
                (f"{victim2} seemed to be hated too: {count2} kicks were received.", None)
            )

    kicks_given = global_stats.get("kicks_given", Counter())
    if kicks_given:
        kicker1, count1 = kicks_given.most_common(1)[0]
        stats.append(
            (
                f"{kicker1} is either insane or just a fair op, kicking a total of {count1} people!",
                None,
            )
        )
        if len(kicks_given) > 1:
            kicker2, count2 = kicks_given.most_common(2)[1]
            stats.append(
                (
                    f"{kicker1}'s faithful follower, {kicker2}, kicked about {count2} people.",
                    None,
                )
            )

    op_give = global_stats.get("op_give_count", 0)
    op_take = global_stats.get("op_take_count", 0)
    if op_give == 0:
        stats.append((f"Strange, no op was given on {html.escape(channel)}!", None))
    else:
        stats.append((f"Ops were given {op_give} times on {html.escape(channel)}!", None))
    if op_take == 0:
        stats.append((f"Wow, no op was taken on {html.escape(channel)}!", None))
    else:
        stats.append((f"Ops were taken {op_take} times on {html.escape(channel)}!", None))

    actions = global_stats.get("actions", Counter())
    if actions:
        act1, cnt1 = actions.most_common(1)[0]
        example = global_stats.get("action_examples", {}).get(act1)
        stats.append(
            (f"{act1} always lets us know what they're doing: {cnt1} actions!", example)
        )
        if len(actions) > 1:
            act2, cnt2 = actions.most_common(2)[1]
            stats.append(
                (f"Also, {act2} tells us what's up with {cnt2} actions.", None)
            )

    monologues = global_stats.get("monologues", Counter())
    if monologues:
        mono1, mc1 = monologues.most_common(1)[0]
        stats.append(
            (
                f"{mono1} talks to themselves a lot. They wrote over 5 lines in a row {mc1} times!",
                None,
            )
        )
        if len(monologues) > 1:
            mono2, mc2 = monologues.most_common(2)[1]
            stats.append(
                (f"Another lonely one was {mono2}, who managed to hit {mc2} times.", None)
            )

    joins = global_stats.get("joins", Counter())
    if joins:
        joiner, jc = joins.most_common(1)[0]
        stats.append(
            (
                f"{joiner} couldn't decide whether to stay or go. {jc} joins during this reporting period!",
                None,
            )
        )

    bad_words = global_stats.get("bad_word_counts", Counter())
    if bad_words:
        percentages = []
        for nick, bad in bad_words.items():
            total = global_stats["words_by_user"].get(nick, 0)
            if total:
                percentages.append((nick, bad / total * 100))
        percentages.sort(key=lambda x: x[1], reverse=True)
        if percentages:
            nick1, p1 = percentages[0]
            stats.append(
                (
                    f"{nick1} has quite a potty mouth. {p1:.1f}% words were foul language.",
                    None,
                )
            )
            if len(percentages) > 1:
                nick2, p2 = percentages[1]
                stats.append(
                    (
                        f"{nick2} also makes sailors blush, {p2:.1f}% of the time.",
                        None,
                    )
                )

    if not stats:
        return

    output.append("<section id='other-numbers'>")
    output.append("<h2>Other interesting numbers</h2>")
    output.append("<table>")
    for line, example in stats:
        if example:
            output.append(
                f"<tr><td>{html.escape(line)}<div style='margin-top:4px;font-size:smaller'><code>{html.escape(example)}</code></div></td></tr>"
            )
        else:
            output.append(f"<tr><td>{html.escape(line)}</td></tr>")
    output.append("</table>")
    output.append("</section>")




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
        "word_last_used": {},
        "mention_last_by": {},
        "kicks_received": Counter(),
        "kicks_given": Counter(),
        "kick_examples": {},
        "joins": Counter(),
        "actions": Counter(),
        "action_examples": {},
        "op_give_count": 0,
        "op_take_count": 0,
        "monologues": Counter(),
        "bad_word_counts": Counter(),
        "generation_time": 0,
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
    global_stats["generation_time"] = total_elapsed
    write_html_report(global_stats, path / "index.html")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} /path/to/logdir")
        sys.exit(1)
    main(sys.argv[1])
