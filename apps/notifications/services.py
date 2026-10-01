"""
Notification service — unified interface for creating in-app notifications
and optionally sending email and/or SMS alongside them.

Usage:
    from apps.notifications.services import notify

    notify(
        recipient=user,
        notification_type='MEMBERSHIP_EXPIRY',
        title='Membership expiring soon',
        message='Your membership expires in 3 days.',
        send_email=True,
        send_sms=False,
    )
"""
import json
import logging
from typing import Optional

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from apps.notifications.models import Notification, PushSubscription

logger = logging.getLogger(__name__)

# ── Email templates (plain text fallbacks) ────────────────────────────────────

EMAIL_TEMPLATES = {
    'MEMBERSHIP_EXPIRY': {
        'subject': 'Your FitCore membership is expiring',
        'template': 'notifications/membership_expiry.html',
    },
    'PAYMENT_DUE': {
        'subject': 'Payment reminder — FitCore',
        'template': 'notifications/payment_due.html',
    },
    'PAYMENT_RECEIVED': {
        'subject': 'Payment confirmed — FitCore',
        'template': 'notifications/payment_received.html',
    },
    'WORKOUT_ASSIGNED': {
        'subject': 'New workout plan assigned — FitCore',
        'template': 'notifications/workout_assigned.html',
    },
    'DIET_ASSIGNED': {
        'subject': 'New diet plan assigned — FitCore',
        'template': 'notifications/diet_assigned.html',
    },
    'WELCOME': {
        'subject': 'Welcome to FitCore!',
        'template': 'notifications/welcome.html',
    },
    'INACTIVITY': {
        'subject': 'We miss you at FitCore!',
        'template': 'notifications/inactivity.html',
    },
}


def _send_email(recipient_email: str, subject: str, html_message: str, plain_message: str = ''):
    """Send an email, falling back to console backend in development."""
    try:
        send_mail(
            subject=subject,
            message=plain_message or strip_tags(html_message),
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'FitCore <noreply@fitcore.local>'),
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f'Email sent to {recipient_email}: {subject}')
    except Exception as e:
        logger.error(f'Failed to send email to {recipient_email}: {e}')


def _send_sms(phone: str, message: str):
    """
    Send an SMS. Currently a no-op placeholder.
    Integrate with Twilio, Africa's Talking, or eSewa SMS when ready.
    """
    if not phone:
        return
    # TODO: Integrate with SMS provider
    # Example with Twilio:
    # from twilio.rest import Client
    # client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    # client.messages.create(body=message, from_=settings.TWILIO_PHONE_NUMBER, to=phone)
    logger.info(f'SMS (placeholder) to {phone}: {message[:50]}...')


# ── Web Push ────────────────────────────────────────────────────────────────

# Page each notification type deep-links to when the user taps the push.
_PUSH_PAGES = {
    'MEMBERSHIP_EXPIRY': 'my-memberships.html',
    'MEMBERSHIP_RENEWAL': 'my-memberships.html',
    'PAYMENT_DUE': 'my-payments.html',
    'PAYMENT_RECEIVED': 'my-payments.html',
    'INACTIVITY': 'my-attendance.html',
    'WORKOUT_REMINDER': 'my-workouts.html',
    'WORKOUT_ASSIGNED': 'my-workouts.html',
    'MEMBER_MESSAGE': 'my-messages.html',
    'TRAINER_REPLY': 'my-messages.html',
    'TRAINER_ASSIGNED': 'my-trainer.html',
}


def _push_url(notification_type: str, notification_id: Optional[int] = None) -> str:
    """Absolute deep link for a tapped notification.

    With a notification id the tap opens that notification's DETAIL page
    (notification-detail.html?id=<id>). Without one it falls back to the
    type's list page, then the inbox.
    """
    base = (getattr(settings, 'FRONTEND_URL', '') or '').rstrip('/')
    if notification_id is not None:
        page = f'notification-detail.html?id={int(notification_id)}'
    else:
        page = _PUSH_PAGES.get(notification_type, 'notifications.html')
    return f'{base}/{page}' if base else f'/{page}'


def send_push(
    recipient,
    title: str,
    message: str,
    notification_type: str = 'GENERAL',
    notification_id: Optional[int] = None,
) -> int:
    """
    Best-effort Web Push to every device the recipient subscribed with.

    Returns the number of deliveries. Never raises — push is a bonus channel,
    the in-app notification row is what matters. Subscriptions that the push
    service has expired (HTTP 404/410) are deleted as they are hit.
    """
    if not (getattr(settings, 'VAPID_PUBLIC_KEY', '') and getattr(settings, 'VAPID_PRIVATE_KEY', '')):
        return 0  # Web Push not configured on this deployment
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning('pywebpush is not installed — skipping Web Push (pip install pywebpush)')
        return 0

    payload = json.dumps({
        'title': title,
        'body': (message or '')[:400],
        'icon': '/logo.png',
        'badge': '/icons/icon-192.png',
        'tag': notification_type,
        'url': _push_url(notification_type, notification_id),
    })
    delivered = 0
    for sub in PushSubscription.objects.filter(user=recipient):
        try:
            webpush(
                subscription_info={
                    'endpoint': sub.endpoint,
                    'keys': {'p256dh': sub.p256dh, 'auth': sub.auth},
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={'sub': settings.VAPID_SUBJECT},
                ttl=24 * 60 * 60,
                timeout=10,
            )
            delivered += 1
        except WebPushException as exc:
            code = exc.response.status_code if getattr(exc, 'response', None) is not None else None
            if code in (404, 410):
                sub.delete()  # push service says this subscription is dead
                logger.info(f'Web Push: removed expired subscription for user {recipient.pk}')
            else:
                logger.warning(f'Web Push failed for user {recipient.pk}: {exc}')
        except Exception as exc:  # noqa: BLE001 — must never raise to the caller
            logger.warning(f'Web Push error for user {recipient.pk}: {exc}')
    return delivered


def notify(
    recipient,
    notification_type: str,
    title: str,
    message: str,
    send_email: bool = True,
    send_sms: bool = False,
    related_membership_id: Optional[int] = None,
    related_payment_id: Optional[int] = None,
    gym=None,
    branch=None,
):
    """
    Create an in-app notification and optionally send email/SMS.

    Args:
        recipient: User instance or user ID
        notification_type: One of Notification.NotificationType values
        title: Short notification title
        message: Full notification body
        send_email: Whether to also send an email
        send_sms: Whether to also send an SMS
        related_membership_id: Optional link to a membership
        related_payment_id: Optional link to a payment
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()

    # Resolve user if ID was passed
    if isinstance(recipient, int):
        recipient = User.objects.get(pk=recipient)

    # Background callers should pass the tenant explicitly. As a compatibility
    # fallback, infer it only when the recipient has exactly one active gym.
    if gym is None:
        memberships = list(
            recipient.gym_memberships.filter(
                status='ACTIVE', gym__status__in=['ACTIVE', 'TRIAL'],
            ).select_related('gym')
        )
        if len(memberships) == 1:
            gym = memberships[0].gym
            if branch is None:
                access = memberships[0].branch_memberships.select_related('branch').first()
                branch = access.branch if access else None

    # 1. Create in-app notification
    notification = Notification.objects.create(
        gym=gym,
        branch=branch,
        recipient=recipient,
        notification_type=notification_type,
        title=title,
        message=message,
        related_membership_id=related_membership_id,
        related_payment_id=related_payment_id,
    )

    # 2. Web Push to the recipient's installed devices. Deferred until the
    #    surrounding transaction commits (never push for a rolled-back row)
    #    and wrapped so a push failure can never break the caller.
    def _push_now():
        try:
            send_push(recipient, title, message, notification_type, notification.pk)
        except Exception as exc:  # noqa: BLE001 — push must never break the caller  # pragma: no cover
            logger.warning(f'Web Push dispatch failed for user {getattr(recipient, "pk", recipient)}: {exc}')

    transaction.on_commit(_push_now)

    # 3. Send email if requested
    if send_email and recipient.email:
        template_info = EMAIL_TEMPLATES.get(notification_type)
        if template_info:
            html_message = render_to_string(template_info['template'], {
                'user': recipient,
                'title': title,
                'message': message,
                'notification': notification,
                'frontend_url': getattr(settings, 'FRONTEND_URL', 'http://localhost:5500'),
            })
            _send_email(recipient.email, template_info['subject'], html_message)
        else:
            # Fallback: send plain email with the notification content
            html_message = f"""
            <div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
                <h2 style="color:#e63946;">{title}</h2>
                <p>{message}</p>
                <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0;">
                <p style="color:#6b7280;font-size:0.85rem;">— FitCore Gym Management</p>
            </div>
            """
            _send_email(recipient.email, title, html_message)

    # 4. Send SMS if requested
    if send_sms and recipient.phone:
        _send_sms(recipient.phone, f'{title}\n\n{message}')

    return notification


def notify_membership_expiry_warning(recipient, days_left: int, plan_name: str, end_date, gym=None, branch=None):
    """Send membership expiry warning at 7, 3, and 1 day marks."""
    urgency = 'tomorrow' if days_left == 1 else f'in {days_left} days'
    title = f'Membership expiring {urgency}'
    message = (
        f'Hi {recipient.get_full_name()},\n\n'
        f'Your {plan_name} membership expires on {end_date} ({days_left} day{"s" if days_left > 1 else ""} left).\n\n'
        f'Please visit the gym or log in to renew your membership before it expires.\n\n'
        f'— FitCore Team'
    )
    return notify(
        recipient=recipient,
        notification_type=Notification.NotificationType.MEMBERSHIP_EXPIRY,
        title=title,
        message=message,
        send_email=True,
        send_sms=days_left <= 1,
        gym=gym,
        branch=branch,
    )


def notify_payment_received(recipient, amount, payment_for, receipt_number, gym=None, branch=None):
    """Notify member that their payment was received."""
    title = f'Payment of NPR {amount:,.0f} received'
    message = (
        f'Hi {recipient.get_full_name()},\n\n'
        f'We received your payment of NPR {amount:,.0f} for {payment_for}.\n'
        f'Receipt number: {receipt_number}\n\n'
        f'Thank you for your payment!\n\n'
        f'— FitCore Team'
    )
    return notify(
        recipient=recipient,
        notification_type=Notification.NotificationType.PAYMENT_RECEIVED,
        title=title,
        message=message,
        send_email=True,
        send_sms=False,
        gym=gym,
        branch=branch,
    )


def notify_payment_due(recipient, amount, payment_for, days_overdue=0, gym=None, branch=None):
    """Notify member about pending payment."""
    if days_overdue > 0:
        title = f'Payment of NPR {amount:,.0f} overdue by {days_overdue} days'
    else:
        title = f'Payment of NPR {amount:,.0f} pending'
    message = (
        f'Hi {recipient.get_full_name()},\n\n'
        f'You have a pending payment of NPR {amount:,.0f} for {payment_for}.\n'
        f'Please visit the gym or contact us to complete your payment.\n\n'
        f'— FitCore Team'
    )
    return notify(
        recipient=recipient,
        notification_type=Notification.NotificationType.PAYMENT_DUE,
        title=title,
        message=message,
        send_email=True,
        send_sms=days_overdue >= 3,
        gym=gym,
        branch=branch,
    )


def notify_welcome(recipient, gym=None, branch=None):
    """Send welcome email after registration."""
    title = 'Welcome to FitCore!'
    message = (
        f'Hi {recipient.get_full_name()},\n\n'
        f'Welcome to FitCore! Your account has been created successfully.\n\n'
        f'You can now:\n'
        f'• View your membership status\n'
        f'• Track your attendance\n'
        f'• See your workout and diet plans\n'
        f'• Monitor your progress\n\n'
        f'If you have any questions, feel free to ask at the front desk.\n\n'
        f'— FitCore Team'
    )
    return notify(
        recipient=recipient,
        notification_type=Notification.NotificationType.GENERAL,
        title=title,
        message=message,
        send_email=True,
        send_sms=False,
        gym=gym,
        branch=branch,
    )


def notify_workout_assigned(recipient, template_name, trainer_name, gym=None, branch=None):
    """Notify member when a trainer assigns a workout."""
    title = f'New workout assigned: {template_name}'
    message = (
        f'Hi {recipient.get_full_name()},\n\n'
        f'Your trainer {trainer_name} has assigned you a new workout plan: {template_name}.\n\n'
        f'Log in to view your workout details and start training!\n\n'
        f'— FitCore Team'
    )
    return notify(
        recipient=recipient,
        notification_type=Notification.NotificationType.WORKOUT_REMINDER,
        title=title,
        message=message,
        send_email=True,
        send_sms=False,
        gym=gym,
        branch=branch,
    )


def notify_diet_assigned(recipient, plan_name, trainer_name, gym=None, branch=None):
    """Notify member when a trainer assigns a diet plan."""
    title = f'New diet plan assigned: {plan_name}'
    message = (
        f'Hi {recipient.get_full_name()},\n\n'
        f'Your trainer {trainer_name} has created a diet plan for you: {plan_name}.\n\n'
        f'Log in to view your meal details and nutrition targets.\n\n'
        f'— FitCore Team'
    )
    return notify(
        recipient=recipient,
        notification_type=Notification.NotificationType.GENERAL,
        title=title,
        message=message,
        send_email=True,
        send_sms=False,
        gym=gym,
        branch=branch,
    )
