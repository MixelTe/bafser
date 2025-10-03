from bafser_tgapi import configure_webhook, setup  # type: ignore


def main(set: bool = True, dev: bool = False):
    setup(dev=dev)
    configure_webhook(set)


def run(args: list[str]):
    if (len(args) == 1 or len(args) == 2 and args[1] == "dev") and args[0] in ("set", "delete"):
        main(args[0] == "set", args[-1] == "dev")
    else:
        print("configure_webhook: <set|delete> [dev]")
