import logging
import sys
import os

def raise_critical(message: str, exc_type=RuntimeError):
    """
    Log a critical error and raise an exception (default RuntimeError).
    Usage: raise_critical("Bad config")  # never returns
    """
    logging.critical(message)
    raise exc_type(message)

    
IMPORTANT_LEVEL_NUM = 25  # Between INFO (20) and WARNING (30)
logging.addLevelName(IMPORTANT_LEVEL_NUM, "IMPORTANT")

def important(self, msg, *args, **kwargs):
    if self.isEnabledFor(IMPORTANT_LEVEL_NUM):
        self._log(IMPORTANT_LEVEL_NUM, msg, args, **kwargs)

logging.Logger.important = important  # instance method
def _root_important(msg, *args, **kwargs):
    logging.log(IMPORTANT_LEVEL_NUM, msg, *args, **kwargs)
logging.important = _root_important   # convenience function

class ColorFormatter(logging.Formatter):
    COLOR_MAP = {
        "DEBUG": "\033[37m",
        "INFO": "\033[36m",
        "IMPORTANT": "\033[1;32m",   # bold bright green
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[41m",
    }
    RESET = "\033[0m"

    def format(self, record):
        if not sys.stdout.isatty() or os.getenv("NO_COLOR"):
            return super().format(record)
        color = self.COLOR_MAP.get(record.levelname, "")
        base = super().format(record)
        return f"{color}{base}{self.RESET}"

def setup_logging(level=logging.INFO):
    root = logging.getLogger()
    # Avoid re-adding if already configured
    if any(isinstance(h, logging.StreamHandler) and getattr(getattr(h, "formatter", None), "__class__", None).__name__ == "ColorFormatter" for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(ColorFormatter("[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    root.handlers = [handler]
    root.setLevel(level)