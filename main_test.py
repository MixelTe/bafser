import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(current, "src"))

from bafser import AppConfig, create_app


app, run = create_app(__name__, AppConfig(
    FRONTEND_FOLDER="test/build",
    # PAGE404="404.html",
    MESSAGE_TO_FRONTEND="",
    DEV_MODE="dev" in sys.argv,
    DELAY_MODE="delay" in sys.argv,
))


# run(False, lambda: init_values(True))
run(__name__ == "__main__", port=5000)
