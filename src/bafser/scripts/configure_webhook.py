from bafser_tgapi import configure_webhook  # type: ignore

import bafser_config


def main(set: bool = True, dev: bool = False):
    configure_webhook(set, config_path=bafser_config.config_dev_path if dev else bafser_config.config_path)  # type: ignore


def run(args: list[str]):
    if (len(args) == 1 or len(args) == 2 and args[1] == "dev") and args[0] in ("set", "delete"):
        main(args[0] == "set", args[-1] == "dev")
    else:
        print("configure_webhook: <set|delete> [dev]")
