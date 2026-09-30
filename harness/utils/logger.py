"""
金枢 2.0 (Jin-Shu OS) - Standard Logging Utility
================================================
为评测支架提供标准化的分级日志输出，替代零散的 print() 语句。
"""

import logging
import sys

def get_harness_logger(name: str = "Harness") -> logging.Logger:
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

# 全局默认 logger
logger = get_harness_logger()
