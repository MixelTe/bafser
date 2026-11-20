from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
STORAGE_DIR = PROJECT_DIR / "storage"

# ---------- tgapi ----------
log_bot_path = str(STORAGE_DIR / "logs/bot.csv")
# bafser_tgapi also turns this relative directory into an import name.
# Run that integration from PROJECT_DIR until its discovery API is updated.
bot_folder = "bot"
config_path = str(PROJECT_DIR / "config.txt")
config_dev_path = str(PROJECT_DIR / "config_dev.txt")
