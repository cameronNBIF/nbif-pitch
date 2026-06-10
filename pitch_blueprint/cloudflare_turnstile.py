"""
turnstile.py
Cloudflare Turnstile CAPTCHA verification.
Verifies the token submitted by the client-side widget with Cloudflare's API.
"""

import logging
import requests

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify_turnstile_token(
    token: str,
    secret_key: str,
    remote_ip: str | None = None,
) -> bool:
    """
    Verify a Cloudflare Turnstile token server-side.

    Args:
        token: The cf-turnstile-response token from the form submission.
        secret_key: The Turnstile secret key (from Key Vault / app settings).
        remote_ip: Optional IP address of the client for additional validation.

    Returns:
        True if the token is valid, False otherwise.
    """
    if not token:
        logger.warning("Turnstile verification failed: no token provided.")
        return False

    payload = {
        "secret": secret_key,
        "response": token,
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        response = requests.post(SITEVERIFY_URL, data=payload, timeout=10)
        response.raise_for_status()
        result = response.json()

        success = result.get("success", False)

        if not success:
            error_codes = result.get("error-codes", [])
            logger.warning(
                f"Turnstile verification failed. "
                f"Error codes: {error_codes}"
            )
        else:
            logger.info("Turnstile verification succeeded.")

        return success

    except requests.RequestException as e:
        logger.error(f"Turnstile verification request failed: {e}")
        return False