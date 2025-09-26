import sys

from bafser_tgapi import configure_webhook  # type: ignore


def main(set: bool = True, dev: bool = False):
    configure_webhook(set, config_path="config_dev.txt" if dev else "config.txt")


if __name__ == "__main__":
    if (len(sys.argv) == 2 or len(sys.argv) == 3 and sys.argv[2] == "dev") and sys.argv[1] in ("set", "delete"):
        main(sys.argv[1] == "set", sys.argv[-1] == "dev")
    else:
        print("configure_webhook: <set|delete> [dev]")
