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
import logging
from typing import Optional

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from apps.notifications.models import Notification

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


def notify(
    recipient,
    notification_type: str,
    title: str,
    message: str,
    send_email: bool = True,
    send_sms: bool = False,
    related_membership_id: Optional[int] = None,
    related_payment_id: Optional[int] = None,
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

    # 1. Create in-app notification
    notification = Notification.objects.create(
        recipient=recipient,
        notification_type=notification_type,
        title=title,
        message=message,
        related_membership_id=related_membership_id,
        related_payment_id=related_payment_id,
    )

    # 2. Send email if requested
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

    # 3. Send SMS if requested
    if send_sms and recipient.phone:
        _send_sms(recipient.phone, f'{title}\n\n{message}')

    return notification


def notify_membership_expiry_warning(recipient, days_left: int, plan_name: str, end_date):
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
    )


def notify_payment_received(recipient, amount, payment_for, receipt_number):
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
    )


def notify_payment_due(recipient, amount, payment_for, days_overdue=0):
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
    )


def notify_welcome(recipient):
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
    )


def notify_workout_assigned(recipient, template_name, trainer_name):
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
    )


def notify_diet_assigned(recipient, plan_name, trainer_name):
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
    )
