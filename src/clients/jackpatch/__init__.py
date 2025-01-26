import logging

_logger = logging.getLogger(__name__)
_log_handler = logging.StreamHandler()
_log_handler.setFormatter(logging.Formatter(
    f"%(name)s - %(levelname)s - %(message)s"))
_logger.setLevel(logging.WARNING)
_logger.addHandler(_log_handler)
