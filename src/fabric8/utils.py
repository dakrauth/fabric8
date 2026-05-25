import os
import sys
import logging
import traceback
from datetime import datetime
from functools import partial

import termcolor

colored = partial(
    termcolor.colored,
    color="white",
    on_color=os.getenv("F8_BG", "on_green"),
    attrs=["bold"]
)

SPREFIX = "☁️ ►►► "
LOG_ABBRS = {
    "DEBUG": "DBG",
    "INFO": "INF",
    "WARNING": "WRN",
    "ERROR": "ERR",
    "CRITICAL": "CRT",
}
LOG_EMOJIS = {
    "DEBUG": "🐞",
    "INFO": "ℹ️",
    "WARNING": "⚠️",
    "ERROR": "⛔️",
    "CRITICAL": "📛",
}



def logger():
    class Formatter(logging.Formatter):
        def format(self, record):
            record.abbr = LOG_EMOJIS.get(record.levelname, record.levelname)
            return super().format(record)

    logger = logging.getLogger("fabfile")
    logger.setLevel(logging.DEBUG)

    stream = logging.StreamHandler(sys.stdout)
    stream.setLevel(logging.INFO)
    stream.setFormatter(Formatter("[{abbr}] {message}", style="{"))
    logger.addHandler(stream)

    file = logging.FileHandler(filename="temp/fabfile.log", mode="a")
    file.setLevel(logging.DEBUG)
    file.setFormatter(
        Formatter(
            "[{abbr} {asctime} {funcName}:{lineno}] {message}",
            datefmt="%Y-%m-%d %H:%M:%S",
            style="{",
        )
    )
    logger.addHandler(file)
    return logger


logger = logger()
log = logger.info
debug = logger.debug
warn = logger.warning
error = logger.error


def log_tb():
    st = traceback.extract_stack()
    log(
        "fabfile trace:\n"
        + "\n".join(
            [
                "{}:{}:{}".format(f.filename.partition("/fabfile/")[-1], f.name, f.lineno)
                for f in st
                if "/fabfile/" in f.filename
            ]
        )
    )


def version_timestamp():
    fmt = "%y%m%d%H%M%S"
    return datetime.utcnow().strftime(fmt)


def banner(msg, level=1):
    msg = colored(f" {msg}") if level == 0 else f" {msg}"
    pre = colored(SPREFIX)
    print(f"\n{pre}{msg}")


def wait_for(expected):
    while True:
        val = input(f"Type {expected} to continue: ")
        if val == expected:
            break
