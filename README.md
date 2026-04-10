# Masters Leaderboard (Live Web Page)

This program runs a local web server that shows The Masters leaderboard.
The page auto-refreshes every 60 seconds.

Features:

- Click any player row to view hole-by-hole scores for that player's active round.
- Leaderboard highlights:
	- top 3 lowest scores for the day
	- top 3 highest scores for the day
- Separate hole-average panel shows average score for each hole in the current round.
- Click Open Pop-Out to open hole averages in a separate browser window.
- Use the hole filter buttons (Show all holes / Top 3 highest avg / Top 3 lowest avg) to focus that table.
- Hole-average highlights:
	- top 3 highest-average (hardest) holes
	- top 3 lowest-average (easiest) holes

## Run

```powershell
c:/python313/python.exe "h:/VS Studio/masters/masters_leaderboard.py"
```

Then open:

- http://127.0.0.1:8000

If port 8000 is already in use, the app automatically moves to the next available port and prints the URL in the terminal.

## Options

- `--host 127.0.0.1` host/interface to bind
- `--port 8000` port to run the web server
- `--top 30` how many leaderboard rows to show
- `--timeout 10` HTTP timeout in seconds
- `--url <feed-url>` override the feed endpoint

Example:

```powershell
c:/python313/python.exe "h:/VS Studio/masters/masters_leaderboard.py" --port 8080 --top 40
```

Stop with Ctrl+C.
