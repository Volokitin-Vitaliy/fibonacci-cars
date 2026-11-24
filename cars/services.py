from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from . import notifications
from .models import Car


def expire_listings():
    """Mark user listings whose month is over as inactive.

    Visibility does not depend on this job (see CarQuerySet.visible), it only
    keeps the stored status in sync and returns how many listings expired."""
    return (Car.objects
            .filter(source=Car.Source.USER, status=Car.Status.ACTIVE,
                    active_until__lte=timezone.now())
            .update(status=Car.Status.INACTIVE))


def send_expiry_reminders():
    """Email owners whose listing expires within LISTING_REMINDER_DAYS.
    Each listing period gets one reminder."""
    now = timezone.now()
    cars = (Car.objects
            .filter(source=Car.Source.USER, status=Car.Status.ACTIVE,
                    moderation=Car.Moderation.APPROVED, reminder_sent_at__isnull=True,
                    active_until__gt=now,
                    active_until__lte=now + timedelta(days=settings.LISTING_REMINDER_DAYS))
            .select_related('owner', 'make'))
    sent = 0
    for car in cars:
        if notifications.notify_expiring(car):
            car.reminder_sent_at = now
            car.save(update_fields=['reminder_sent_at'])
            sent += 1
    return sent


def submit_for_review(car):
    """Put a new or edited user listing into moderation (if enabled)."""
    if not settings.LISTING_MODERATION:
        car.moderation = Car.Moderation.APPROVED
        car.save(update_fields=['moderation', 'updated_at'])
        return False
    car.moderation = Car.Moderation.PENDING
    car.rejection_reason = ''
    car.save(update_fields=['moderation', 'rejection_reason', 'updated_at'])
    notifications.notify_moderators(car)
    return True


def approve(car):
    """Approve a listing. A listing that has never run starts its first month
    now: the month paid at submission, or a free one when payments are off."""
    from . import payments

    car.moderation = Car.Moderation.APPROVED
    car.rejection_reason = ''
    car.save(update_fields=['moderation', 'rejection_reason', 'updated_at'])
    if not car.is_listing_active:
        paid = payments.unused_payment(car)
        if paid:
            payments.use_payment(car, paid)
        elif car.activated_at is None and not settings.LISTING_PAYMENT_REQUIRED:
            car.activate()
    notifications.notify_approved(car)


def reject(car, reason=''):
    car.moderation = Car.Moderation.REJECTED
    car.rejection_reason = reason
    car.save(update_fields=['moderation', 'rejection_reason', 'updated_at'])
    notifications.notify_rejected(car)
