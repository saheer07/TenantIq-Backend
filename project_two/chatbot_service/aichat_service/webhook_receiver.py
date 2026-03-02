"""
chatbot_service/aichat_service/webhook_receiver.py

Validates incoming webhook requests from document service.
Used inside DocumentIndexWebhookView in views.py.
"""

import hashlib
import hmac
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class WebhookReceiver:
    """
    Validates HMAC-SHA256 signatures and API keys
    on incoming webhook requests.
    """

    def __init__(self):
        self.secret_key = getattr(settings, 'WEBHOOK_API_KEY', '').strip()

    def validate(self, request) -> tuple:
        """
        Validate an incoming webhook request.

        Returns:
            (True,  '')       → request is authentic
            (False, 'reason') → request rejected
        """
        if not self.secret_key:
            logger.error(
                "[RECEIVER] WEBHOOK_API_KEY not set in settings! "
                "All webhook requests will be rejected."
            )
            return False, "Server misconfiguration"

        # ── Step 1: API key check ──
        api_key = (
            request.META.get('HTTP_X_API_KEY', '').strip()
            or request.META.get('HTTP_X_Api_Key', '').strip()
        )

        if not api_key:
            logger.warning(
                "[RECEIVER] Missing API key. "
                f"Headers present: {[k for k in request.META if k.startswith('HTTP_')]}"
            )
            return False, "Missing X-API-Key header"

        if api_key != self.secret_key:
            logger.warning(
                f"[RECEIVER] API key mismatch. "
                f"Got='{api_key[:8]}...' Expected='{self.secret_key[:8]}...'"
            )
            return False, "Invalid API key"

        # ── Step 2: HMAC signature check (if header present) ──
        signature = request.META.get('HTTP_X_WEBHOOK_SIGNATURE', '').strip()
        if signature:
            try:
                body = request.body.decode('utf-8')
                expected = hmac.new(
                    self.secret_key.encode('utf-8'),
                    body.encode('utf-8'),
                    hashlib.sha256,
                ).hexdigest()

                if not hmac.compare_digest(signature, expected):
                    logger.warning("[RECEIVER] HMAC signature mismatch — request may be tampered")
                    return False, "Invalid HMAC signature"

                logger.debug("[RECEIVER] HMAC signature verified ✓")

            except Exception as e:
                # Log but don't block — API key already verified
                logger.warning(f"[RECEIVER] Signature check error (non-fatal): {e}")

        # ── Step 3: Log delivery metadata ──
        delivery_id = request.META.get('HTTP_X_WEBHOOK_DELIVERY', 'unknown')
        event_type  = request.META.get('HTTP_X_WEBHOOK_EVENT', 'unknown')
        timestamp   = request.META.get('HTTP_X_WEBHOOK_TIMESTAMP', 'unknown')

        logger.info(
            f"[RECEIVER] ✓ Valid webhook — "
            f"event='{event_type}' "
            f"delivery={delivery_id} "
            f"timestamp={timestamp}"
        )

        return True, ""


# Singleton — import this in views.py
webhook_receiver = WebhookReceiver()