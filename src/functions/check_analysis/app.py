"""check_analysis — reports analysis completion status.

The reachability analyzer is synchronous, so by the time ``run_analysis``
returns all scopes are already analyzed. This function simply reports
completion and provides a seam for a future asynchronous analysis backend.
"""
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    logger.info("Analysis is complete (synchronous engine); no polling required.")
    return True
