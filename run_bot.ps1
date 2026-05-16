$ErrorActionPreference = "Stop"
if (!(Test-Path ".venv")) {
  python -m venv .venv
}
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m bulk_auto_bot.main --debug-scores
