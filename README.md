# pyircstats

A fast, modern IRC channel log analyzer written in Python. Inspired by `pisg`, but built to work cleanly with ZNC-style and EnergyMech logs, Discord relay bots, and daily rotating log files. Outputs a static `index.html` report with nick stats, quotes, recent topics, and more.

## Features

- 📅 Parses daily `.log` files in ZNC or EnergyMech format  
- 🔎 Extracts nick activity, mentions, quotes, and last seen  
- 💬 Tracks topics, URLs, and Discord relays
- 📝 Counts common words, smileys, and daily activity trends, showing who last used top words (excluding nicknames) and who last mentioned each nick
- 🚫 Skips common stop words like "the" and "and" in top-word stats (extend via `IGNOREWORDS`)
- ⚡ Caches per-log results for fast reprocessing
- 🌐 Generates a clean, single-file HTML report (`index.html`) with a modern, pisg-inspired UI, centered summary header, and color-coded activity charts
- ⏱️ Shows overall hourly activity and stacked per-user bars to visualize when conversations happen
- 🧠 Intelligent random quote selection and "last seen" summaries
- 🔌 Bridge bot handling via `BRIDGENICKS` to rewrite relayed nicks
- 🤖 Ignore typical Anope services (NickServ, ChanServ, etc.) and any extra bots via `BOTNICKS` so automated chatter doesn't skew stats
- 🔁 Merge alternate nick spellings via `NICKALIASES` so renamed users share stats
- 🔢 "Other interesting numbers" section for kicks, joins, ops, monologues, and profanity, plus a stats footer with total lines and generation time (action counts only include `/me` commands)
- 🤬 Optional [`profanity-check`](https://pypi.org/project/profanity-check/) integration for smarter foul-language stats
- ⚙️ Optional config file (`pisg`-style) to define bot lists, nick aliases, genders, ignored nicks, bridge bots, and extra stop words

## Example Stats Output

| # | Nick         | Mentions | Last Seen | Random Quote                                |
|---|--------------|----------|------------|---------------------------------------------|
| 1 | chugdiesel   | 448,030  | yesterday  | "network n it comes crashing down"          |
| 2 | antiroach    | 304,279  | today      | "im fine what happened bros"                |
| 3 | Rusty        | 193,974  | today      | "interesting, i was never a huge xfiles guy"|

## Requirements

- Python 3.8+
- Optional: [`profanity-check`](https://pypi.org/project/profanity-check/) for profanity detection

## Usage

```bash
# Clone the repo
git clone https://github.com/youruser/pyircstats.git
cd pyircstats

# Run it on your log directory
python3 ircstats.py /path/to/your/logs/

# or provide a config file with bot lists, aliases, genders, etc.
python3 ircstats.py /path/to/your/logs/ myconfig.cfg

# with bridge bots (comma-separated)
BRIDGENICKS=matrixbridge,discordbot python3 ircstats.py /path/to/your/logs/

# ignore additional bot accounts (Anope services are skipped by default)
BOTNICKS=SomeBot python3 ircstats.py /path/to/your/logs/

# ignore additional common words
IGNOREWORDS=foo,bar python3 ircstats.py /path/to/your/logs/

# merge nick aliases
NICKALIASES=rc=rustycloud,rusty_=rustycloud python3 ircstats.py /path/to/your/logs/
```

### Sample config file

```ini
[bots]
# additional bots beyond default services
nicks = SomeBot

[aliases]
rc = rustycloud
rusty_ = rustycloud

[ignore]
nicks = badguy,spammer

[ignorewords]
words = foo,bar

[bridge]
nicks = matrixbridge,discordbot

[users]
rustycloud = male
alice = female
somebot = bot
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
- Docker support

## License

MIT

## Credits

Built by Rusty — inspired by pisg, but refactored for modern chat archives.
