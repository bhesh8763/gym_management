"""
Khalti ePayment (KPG v2) sandbox integration.

Docs: https://docs.khalti.com/khalti-epayment/
Sandbox base URL: https://dev.khalti.com/api/v2
Get a test secret key by signing up as a merchant at https://test-admin.khalti.com
(sandbox login OTP is always 987654). Set it as KHALTI_SECRET_KEY in .env.

This module only talks to Khalti — it never decides whether a Payment is
"successful". That decision is made in views.py after lookup() is called
and the amount is cross-checked against our own record.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class KhaltiError(Exception):
    """Raised when Khalti's API returns an error or is unreachable."""
    pass


def _headers():
    if not settings.KHALTI_SECRET_KEY:
        raise KhaltiError(
            'KHALTI_SECRET_KEY is not set. Get a test secret key from '
            'test-admin.khalti.com and add it to your .env file.'
        )
    return {
        'Authorization': f'key {settings.KHALTI_SECRET_KEY}',
        'Content-Type': 'application/json',
    }


def initiate_payment(payment):
    """
    Starts a Khalti checkout for the given Payment instance.

    Returns {"pidx": "...", "payment_url": "..."} on success.
    Raises KhaltiError on any failure (network, bad request, missing config).
    """
    member = payment.member
    payload = {
        'return_url': f'{settings.FRONTEND_URL}/my-payments.html',
        'website_url': settings.FRONTEND_URL,
        # Khalti wants amount in paisa (NPR * 100), as a whole number.
        'amount': int(payment.amount * 100),
        'purchase_order_id': f'GYM-PAY-{payment.id}',
        'purchase_order_name': payment.get_payment_for_display(),
        'customer_info': {
            'name': member.get_full_name() or member.email,
            'email': member.email or 'test@khalti.com',
            # Khalti's sandbox only accepts its own test MSISDNs (9800000000-05)
            # for the checkout login step, regardless of what's sent here.
            'phone': member.phone or '9800000001',
        },
    }

    # Include webhook URL so Khalti can notify us server-to-server.
    # This is critical: if the member closes their browser before the
    # return_url redirect, the webhook is the only way to confirm payment.
    webhook_url = getattr(settings, 'KHALTI_WEBHOOK_URL', '')
    if webhook_url:
        payload['webhook_url'] = webhook_url

    try:
        resp = requests.post(
            f'{settings.KHALTI_BASE_URL}/epayment/initiate/',
            json=payload,
            headers=_headers(),
            timeout=15,
        )
    except requests.RequestException as exc:
        raise KhaltiError(f'Could not reach Khalti: {exc}') from exc

    data = resp.json() if resp.content else {}
    if resp.status_code != 200:
        raise KhaltiError(data.get('detail') or data or f'Khalti returned HTTP {resp.status_code}')

    pidx = data.get('pidx')
    payment_url = data.get('payment_url')
    if not pidx or not payment_url:
        raise KhaltiError(f'Unexpected Khalti response: {data}')

    return {'pidx': pidx, 'payment_url': payment_url}


def lookup_payment(pidx):
    """
    Looks up the real status of a Khalti transaction by pidx.

    Returns the raw Khalti response dict, e.g.:
    {"pidx": "...", "total_amount": 200000, "status": "Completed",
     "transaction_id": "...", "fee": 0, "refunded": false}

    Possible `status` values: Completed, Pending, Initiated, Expired,
    User canceled, Refunded, Partially Refunded.

    Raises KhaltiError on network failure or non-200 response.
    """
    try:
        resp = requests.post(
            f'{settings.KHALTI_BASE_URL}/epayment/lookup/',
            json={'pidx': pidx},
            headers=_headers(),
            timeout=15,
        )
    except requests.RequestException as exc:
        raise KhaltiError(f'Could not reach Khalti: {exc}') from exc

    data = resp.json() if resp.content else {}
    if resp.status_code != 200:
        raise KhaltiError(data.get('detail') or data or f'Khalti returned HTTP {resp.status_code}')

    # Validate that the response contains the fields we need
    required_fields = ('pidx', 'status', 'total_amount')
    missing = [f for f in required_fields if f not in data]
    if missing:
        raise KhaltiError(f'Khalti lookup response missing fields: {missing}. Raw: {data}')

    return data


def verify_payment(pidx, expected_amount):
    """
    Convenience wrapper: lookup + validate amount + return status.

    Returns a dict:
    {
        "status": "Completed" | "Pending" | "Expired" | "User canceled" | ...,
        "verified": True/False,
        "transaction_id": "...",
        "raw": {...}
    }

    Raises KhaltiError on network/config issues.
    """
    result = lookup_payment(pidx)

    gateway_status = result.get('status')
    gateway_amount_paisa = result.get('total_amount')
    expected_paisa = int(expected_amount * 100)

    verified = (
        gateway_status == 'Completed'
        and gateway_amount_paisa == expected_paisa
    )

    if gateway_status == 'Completed' and not verified:
        logger.warning(
            'Khalti amount mismatch for pidx=%s: expected %d paisa, got %d',
            pidx, expected_paisa, gateway_amount_paisa,
        )

    return {
        'status': gateway_status,
        'verified': verified,
        'transaction_id': result.get('transaction_id', ''),
        'fee': result.get('fee', 0),
        'refunded': result.get('refunded', False),
        'raw': result,
    }
