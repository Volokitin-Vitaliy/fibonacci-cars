"""Paid listing activation with Stripe Checkout (5 EUR per month)."""

from decimal import Decimal

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Car, Payment


class PaymentsNotConfigured(Exception):
    pass


def _stripe():
    if not settings.STRIPE_SECRET_KEY:
        raise PaymentsNotConfigured
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def create_checkout(car, user, success_url, cancel_url):
    """Create a Stripe Checkout Session for one listing period."""
    amount = Decimal(settings.LISTING_PRICE_EUR)
    session = _stripe().checkout.Session.create(
        mode='payment',
        customer_email=user.email,
        line_items=[{
            'quantity': 1,
            'price_data': {
                'currency': 'eur',
                'unit_amount': int(amount * 100),
                'product_data': {
                    'name': f'FIBONACCI: {car} — {settings.LISTING_DURATION_DAYS} days',
                },
            },
        }],
        metadata={'car_id': str(car.pk), 'user_id': str(user.pk)},
        success_url=success_url + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=cancel_url,
    )
    Payment.objects.create(car=car, user=user, amount=amount, currency='EUR',
                           stripe_session_id=session.id)
    return session.url


def fulfill(session):
    """Activate the listing for a paid session. Safe to call several times
    (webhook and success page may both deliver the same session)."""
    if session.get('payment_status') != 'paid':
        return False
    with transaction.atomic():
        payment = (Payment.objects.select_for_update()
                   .filter(stripe_session_id=session['id']).first())
        if payment is None or payment.status == Payment.Status.PAID:
            return False
        payment.status = Payment.Status.PAID
        payment.paid_at = timezone.now()
        payment.save(update_fields=['status', 'paid_at'])
        car = payment.car
        if car is not None and car.source == Car.Source.USER:
            car.activate(paid_amount=payment.amount, method='stripe')
    return True


def retrieve_session(session_id):
    return _stripe().checkout.Session.retrieve(session_id)


def parse_webhook(payload, signature):
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise PaymentsNotConfigured
    return stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
