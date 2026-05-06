# Data directory

Runtime files live here:

- `bot.sqlite3` — SQLite database created automatically.
- `events.csv` — optional corporate events calendar used by `/events`, `/calendar`, `/brief`, and digest.

To enable events, copy the example:

```bash
cp data/events.example.csv data/events.csv
```

CSV columns:

```csv
date,symbol,category,title,source_url,importance
2026-05-15,SBER,report,Публикация финансовых результатов,https://example.com,high
```
