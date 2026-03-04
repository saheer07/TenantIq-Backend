"""
document_service/doc_service/webhook_sender.py

Production-ready webhook sender with:
  - HMAC-SHA256 signature authentication
  - Exponential backoff retry (3 attempts: 1s -> 2s -> 4s)
  - Full request/response logging
  - Environment-based configuration
"""

import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class WebhookSender:

    MAX_RETRIES = 3
    INITIAL_BACKOFF = 1       # seconds
    BACKOFF_MULTIPLIER = 2    # 1s -> 2s -> 4s
    REQUEST_TIMEOUT = 30      # seconds per attempt

    def __init__(self):
        self.secret_key = getattr(settings, 'WEBHOOK_API_KEY', 'webhook-secret-key-12345').strip()
        self.chatbot_url = getattr(settings, 'CHATBOT_SERVICE_URL', 'http://127.0.0.1:8002').strip()

    # ----------------------------------------------------------
    # PUBLIC -- call this to fire any webhook
    # ----------------------------------------------------------
    def send(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        event_type: str,
        document_id: Optional[str] = None,
    ) -> bool:
        """
        Send a webhook POST with automatic retry.

        Returns True if any attempt succeeded, False after all retries fail.
        """
        delivery_id = str(uuid.uuid4())
        full_payload = self._build_envelope(payload, event_type, delivery_id)
        headers = self._build_headers(full_payload, event_type, delivery_id)

        logger.info(
            f"[WEBHOOK] >> Sending event='{event_type}' "
            f"delivery={delivery_id} -> {endpoint}"
        )

        last_error = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                success = self._attempt(endpoint, full_payload, headers, attempt)
                if success:
                    logger.info(
                        f"[WEBHOOK] OK SUCCESS event='{event_type}' "
                        f"attempt={attempt}/{self.MAX_RETRIES}"
                    )
                    self._set_document_status(document_id, 'processing')
                    return True

                last_error = f"Non-200 response on attempt {attempt}"

            except requests.exceptions.Timeout:
                last_error = f"Timeout on attempt {attempt}"
                logger.warning(f"[WEBHOOK] Timeout attempt={attempt}/{self.MAX_RETRIES}")

            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection refused -- is chatbot service running on port 8002? ({e})"
                logger.error(f"[WEBHOOK] Connection error attempt={attempt}: {e}")

            except _ClientError as e:
                # 4xx errors won't fix themselves -- stop retrying
                logger.error(f"[WEBHOOK] Client error -- not retrying: {e}")
                self._set_document_status(document_id, 'failed')
                return False

            except Exception as e:
                last_error = str(e)
                logger.error(f"[WEBHOOK] Unexpected error attempt={attempt}: {e}")

            # Exponential backoff
            if attempt < self.MAX_RETRIES:
                wait = self.INITIAL_BACKOFF * (self.BACKOFF_MULTIPLIER ** (attempt - 1))
                logger.info(
                    f"[WEBHOOK] Retrying in {wait}s "
                    f"(attempt {attempt + 1}/{self.MAX_RETRIES})..."
                )
                time.sleep(wait)

        logger.error(
            f"[WEBHOOK] FAILED event='{event_type}' "
            f"after {self.MAX_RETRIES} attempts. Last error: {last_error}"
        )
        self._set_document_status(document_id, 'failed')
        return False

    # ----------------------------------------------------------
    # PRIVATE HELPERS
    # ----------------------------------------------------------
    def _attempt(self, endpoint, payload, headers, attempt) -> bool:
        # Use canonical JSON formatting for consistency
        body = json.dumps(
            payload, 
            sort_keys=True, 
            separators=(',', ':'),
            default=str
        )
        logger.debug(f"[WEBHOOK] POST attempt={attempt} -> {endpoint}")

        response = requests.post(
            endpoint,
            data=body.encode('utf-8'),
            headers=headers,
            timeout=self.REQUEST_TIMEOUT,
        )

        logger.info(
            f"[WEBHOOK] Response attempt={attempt} "
            f"status={response.status_code} "
            f"body={response.text[:300]}"
        )

        if 200 <= response.status_code < 300:
            return True

        if 400 <= response.status_code < 500:
            raise _ClientError(
                f"HTTP {response.status_code}: {response.text[:300]}"
            )

        # 5xx -> allow retry
        return False

    def _build_envelope(self, data, event_type, delivery_id) -> Dict:
        """Wrap raw payload in a standard envelope."""
        return {
            "event":       event_type,
            "delivery_id": delivery_id,
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "api_version": "v1",
            "data":        data,
        }

    def _build_headers(self, payload, event_type, delivery_id) -> Dict:
        """Build secure headers with HMAC-SHA256 signature."""
        # Use canonical JSON formatting for signature
        body = json.dumps(
            payload, 
            sort_keys=True, 
            separators=(',', ':'),
            default=str
        )
        signature = self._sign(body)

        return {
            "Content-Type":        "application/json",
            "X-API-Key":           self.secret_key,
            "X-Webhook-Signature": signature,
            "X-Webhook-Event":     event_type,
            "X-Webhook-Delivery":  delivery_id,
            "X-Webhook-Timestamp": datetime.now(timezone.utc).isoformat(),
            "User-Agent":          "TenantIQ-Webhook/1.0",
        }

    def _sign(self, body: str) -> str:
        """HMAC-SHA256 signature of the request body."""
        return hmac.new(
            self.secret_key.encode('utf-8'),
            body.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()

    def _set_document_status(self, document_id: Optional[str], status: str):
        if not document_id:
            return
        try:
            from .models import Document
            Document.objects.filter(id=document_id).update(indexing_status=status)
            logger.info(f"[WEBHOOK] Document {document_id} -> status={status}")
        except Exception as e:
            logger.warning(f"[WEBHOOK] Could not update document status: {e}")


class _ClientError(Exception):
    """Raised for 4xx responses -- these are not retried."""
    pass


# Singleton instance -- import this everywhere
webhook_sender = WebhookSender()