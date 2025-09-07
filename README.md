# pyircstats

A fast, modern IRC channel log analyzer written in Python. Inspired by `pisg`, but built to work cleanly with ZNC-style and EnergyMech logs, Discord relay bots, and daily rotating log files. Outputs a static `index.html` report with nick stats, quotes, recent topics, and more.

## Features

- 📅 Parses daily `.log` files in ZNC or EnergyMech format  
- 🔎 Extracts nick activity, mentions, quotes, and last seen  
- 💬 Tracks topics, URLs, and Discord relays
- 📝 Counts common words, smileys, and daily activity trends
- 🚫 Filters non-nicks and common stopwords from mention stats
- ⚡ Caches per-log results for fast reprocessing  
- 🌐 Generates a clean, single-file HTML report (`index.html`) with a modern, pisg-inspired UI and full pisg-style sections
- 🧠 Intelligent random quote selection and "last seen" summaries  

## Example Stats Output

| # | Nick         | Mentions | Last Seen | Random Quote                                |
|---|--------------|----------|------------|---------------------------------------------|
| 1 | chugdiesel   | 448,030  | yesterday  | "network n it comes crashing down"          |
| 2 | antiroach    | 304,279  | today      | "im fine what happened bros"                |
| 3 | Rusty        | 193,974  | today      | "interesting, i was never a huge xfiles guy"|

## Requirements

- Python 3.8+
- No external dependencies

## Usage

```bash
# Clone the repo
git clone https://github.com/youruser/pyircstats.git
cd pyircstats

# Run it on your log directory
python3 ircstats.py /path/to/your/logs/
```

This will:

- Load or build a cache of known nicks
- Process all `.log` files in the directory (by date)
- Generate or update per-log JSON caches
- Output a `index.html` file with aggregated stats

## File Structure

Logs should be named as `YYYY-MM-DD.log`, e.g.:

```
/logs/
  2025-06-26.log
  2025-06-27.log
  ...
```

Supported formats include:

- `[YYYY-MM-DD HH:MM:SS] <nick> message`
- `[HH:MM:SS] <nick> message` (ZNC-style)
- `[YYYY-MM-DD HH:MM:SS] * nick set the topic to [...]`

## Planned Features

- Export CSV/JSON summaries
- Per-user stat pages
- Tagging known bots
- Docker support

## License

MIT

## Credits

Built by Rusty — inspired by pisg, but refactored for modern chat archives.
