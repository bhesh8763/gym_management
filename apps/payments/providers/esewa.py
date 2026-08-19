"""
eSewa ePay v2 sandbox integration.

Docs: https://developer.esewa.com.np/pages/Epay
Sandbox form action: https://rc-epay.esewa.com.np/api/epay/main/v2/form
Sandbox status-check: https://rc.esewa.com.np/api/epay/transaction/status/
Test merchant code: EPAYTEST — test secret key: 8gBm/:&EnhH.1/q
Set ESEWA_MERCHANT_CODE / ESEWA_SECRET_KEY in .env.

Unlike Khalti (API-first: we call Khalti, get a payment_url, redirect the
member), eSewa ePay v2 is form-submission based: we build a set of signed
fields, the FRONTEND submits an actual HTML form (POST) directly to eSewa's
form action, and eSewa redirects the browser back to our success_url with a
base64-encoded JSON payload in ?data=.

This module never decides whether a Payment is "successful" — it only signs
outgoing requests and verifies eSewa's responses. That decision (marking a
Payment PAID) is made in views.py, same as the Khalti flow.
"""
import base64
import hashlib
import hmac
import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Fields eSewa requires in the signature, in this exact order — the
# signed_field_names value below the signature is itself part of the
# signature payload, so this order must always match what's submitted.
SIGNED_FIELD_NAMES = ('total_amount', 'transaction_uuid', 'product_code')


class EsewaError(Exception):
    """Raised when eSewa's API returns an error, is unreachable, or a
    signature/response fails validation."""
    pass


def _config():
    if not settings.ESEWA_MERCHANT_CODE or not settings.ESEWA_SECRET_KEY:
        raise EsewaError(
            'ESEWA_MERCHANT_CODE / ESEWA_SECRET_KEY are not set. Use the '
            'sandbox test merchant code EPAYTEST and test secret key '
            '8gBm/:&EnhH.1/q in your .env file for development.'
        )
    return settings.ESEWA_MERCHANT_CODE, settings.ESEWA_SECRET_KEY


def _sign(message, secret_key):
    """HMAC-SHA256, base64-encoded — eSewa's required signature format."""
    digest = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode('utf-8')


def build_form_fields(payment):
    """
    Builds the signed field set the FRONTEND must POST as a hidden HTML
    form directly to settings.ESEWA_BASE_URL (eSewa's form action URL).

    Returns a dict of form field name -> value, e.g.:
    {
        "amount": "1000", "tax_amount": "0", "total_amount": "1000",
        "transaction_uuid": "GYM-PAY-42-<uuid4 hex>",
        "product_code": "EPAYTEST",
        "product_service_charge": "0", "product_delivery_charge": "0",
        "success_url": "...", "failure_url": "...",
        "signed_field_names": "total_amount,transaction_uuid,product_code",
        "signature": "...",
    }

    We only ever sign amount == total_amount (no separate tax/service/
    delivery charges), which keeps the signed-fields set fixed and simple.
    Raises EsewaError if merchant credentials are missing.
    """
    merchant_code, secret_key = _config()

    total_amount = f'{payment.amount:.2f}'
    # transaction_uuid must be unique per attempt (not just per Payment),
    # so retries after a failed/expired attempt don't collide with eSewa's
    # own duplicate-transaction_uuid rejection.
    transaction_uuid = f'GYM-PAY-{payment.id}-{payment.transaction_id or _short_uuid()}'

    fields = {
        'amount': total_amount,
        'tax_amount': '0',
        'total_amount': total_amount,
        'transaction_uuid': transaction_uuid,
        'product_code': merchant_code,
        'product_service_charge': '0',
        'product_delivery_charge': '0',
        'success_url': f'{settings.FRONTEND_URL}/my-payments.html',
        'failure_url': f'{settings.FRONTEND_URL}/my-payments.html',
        'signed_field_names': ','.join(SIGNED_FIELD_NAMES),
    }

    message = ','.join(f'{name}={fields[name]}' for name in SIGNED_FIELD_NAMES)
    fields['signature'] = _sign(message, secret_key)

    return fields


def _short_uuid():
    import uuid
    return uuid.uuid4().hex[:12]


def decode_response(data_param):
    """
    Decodes the base64 ?data= query param eSewa appends to success_url /
    failure_url on redirect back to us.

    Returns the parsed dict, e.g.:
    {"transaction_code": "...", "status": "COMPLETE", "total_amount": "1,000.0",
     "transaction_uuid": "...", "product_code": "EPAYTEST",
     "signed_field_names": "...", "signature": "..."}

    Raises EsewaError if the payload isn't valid base64/JSON, or if its own
    signature doesn't verify (anti-tampering check — never trust this data
    without checking it was actually signed by eSewa's secret key first).
    """
    try:
        decoded = base64.b64decode(data_param).decode('utf-8')
        data = json.loads(decoded)
    except Exception as exc:
        raise EsewaError(f'Could not decode eSewa response: {exc}') from exc

    _, secret_key = _config()
    signed_names = data.get('signed_field_names', '')
    field_names = signed_names.split(',') if signed_names else []
    if not field_names:
        raise EsewaError(f'eSewa response missing signed_field_names: {data}')

    try:
        message = ','.join(f'{name}={data[name]}' for name in field_names)
    except KeyError as exc:
        raise EsewaError(f'eSewa response missing signed field {exc}: {data}') from exc

    expected_signature = _sign(message, secret_key)
    if not hmac.compare_digest(expected_signature, data.get('signature', '')):
        raise EsewaError(f'eSewa response signature verification failed: {data}')

    return data


def check_status(transaction_uuid, total_amount):
    """
    Calls eSewa's status-check API directly (defence in depth — never rely
    on the redirect payload alone, since a slow/interrupted redirect can
    leave a payment's real status ambiguous on our end).

    Returns the raw eSewa response dict, e.g.:
    {"product_code": "EPAYTEST", "transaction_uuid": "...",
     "total_amount": 1000.0, "status": "COMPLETE",
     "ref_id": "0000000000"}

    Possible `status` values: COMPLETE, PENDING, FULL_REFUND,
    PARTIAL_REFUND, AMBIGUOUS, NOT_FOUND, CANCELED.

    Raises EsewaError on network failure or non-200 response.
    """
    merchant_code, _ = _config()
    try:
        resp = requests.get(
            settings.ESEWA_STATUS_CHECK_URL,
            params={
                'product_code': merchant_code,
                'transaction_uuid': transaction_uuid,
                'total_amount': total_amount,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise EsewaError(f'Could not reach eSewa: {exc}') from exc

    try:
        data = resp.json() if resp.content else {}
    except (ValueError, KeyError):
        raise EsewaError(f'eSewa returned non-JSON (HTTP {resp.status_code}): {resp.text[:200]}')

    if resp.status_code != 200:
        raise EsewaError(data.get('message') or data or f'eSewa returned HTTP {resp.status_code}')

    if 'status' not in data:
        raise EsewaError(f'eSewa status response missing "status" field. Raw: {data}')

    return data


def verify_payment(transaction_uuid, expected_amount):
    """
    Convenience wrapper: status-check + validate amount + return status.

    Returns a dict:
    {
        "status": "COMPLETE" | "PENDING" | "CANCELED" | ...,
        "verified": True/False,
        "ref_id": "...",
        "raw": {...}
    }

    Raises EsewaError on network/config issues.
    """
    result = check_status(transaction_uuid, expected_amount)

    gateway_status = result.get('status')
    # eSewa returns total_amount as a float/number in the status response.
    gateway_amount = result.get('total_amount')
    verified = (
        gateway_status == 'COMPLETE'
        and gateway_amount is not None
        and float(gateway_amount) == float(expected_amount)
    )

    if gateway_status == 'COMPLETE' and not verified:
        logger.warning(
            'eSewa amount mismatch for transaction_uuid=%s: expected %s, got %s',
            transaction_uuid, expected_amount, gateway_amount,
        )

    return {
        'status': gateway_status,
        'verified': verified,
        'ref_id': result.get('ref_id', ''),
        'raw': result,
    }