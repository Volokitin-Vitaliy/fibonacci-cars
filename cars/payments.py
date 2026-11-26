"""Paid listings: LISTING_PRICE_EUR (10 EUR) for one listing period.

Providers: WayForPay (default) and Stripe Checkout, chosen with
PAYMENT_PROVIDER. A new listing is paid when it is submitted; the paid month
starts when a moderator approves it. An expired listing is paid again when
the owner reactivates it.
"""

import hashlib
import hmac
import json
import time
import uuid
from decimal import Decimal
from urllib.parse import urlparse

import stripe
from django.conf import settings
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .models import Car, Payment

WAYFORPAY_URL = 'https://secure.wayforpay.com/pay'


class PaymentsNotConfigured(Exception):
    pass


def provider():
    return settings.PAYMENT_PROVIDER


def is_configured():
    if provider() == Payment.Provider.WAYFORPAY:
        return bool(settings.WAYFORPAY_MERCHANT_ACCOUNT and settings.WAYFORPAY_SECRET_KEY)
    return bool(settings.STRIPE_SECRET_KEY)


def required_for(user):
    """Whether this user pays for listings. Site staff (admins) post for free, so they
    can test the whole flow, moderation included."""
    return settings.LISTING_PAYMENT_REQUIRED and not getattr(user, 'is_staff', False)


def price():
    return Decimal(settings.LISTING_PRICE_EUR).quantize(Decimal('0.01'))


def start(request, car):
    """Create a payment for the car and send the user to the payment page."""
    if not is_configured():
        raise PaymentsNotConfigured
    if provider() == Payment.Provider.WAYFORPAY:
        return _wayforpay_start(request, car)
    return redirect(_stripe_start(request, car))


# --- Fulfilment (shared) -----------------------------------------------------

def fulfill(reference, paid):
    """Record the outcome of a payment. Safe to call several times: the
    callback and the return page may both report the same payment."""
    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(reference=reference).first()
        if payment is None or payment.status == Payment.Status.PAID:
            return payment
        if not paid:
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=['status'])
            return payment
        payment.status = Payment.Status.PAID
        payment.paid_at = timezone.now()
        payment.save(update_fields=['status', 'paid_at'])
        if payment.car is not None:
            apply_to_car(payment)
    return payment


def apply_to_car(payment):
    from . import services

    car = payment.car
    if car.moderation == Car.Moderation.AWAITING_PAYMENT:
        # New listing: it goes to review; the paid month starts on approval.
        if not services.submit_for_review(car):
            use_payment(car, payment)
    elif car.is_approved and not car.is_listing_active:
        use_payment(car, payment)


def use_payment(car, payment):
    car.activate(paid_amount=payment.amount, method=payment.provider)
    Payment.objects.filter(pk=payment.pk).update(used_at=timezone.now())


def unused_payment(car):
    return (car.payments.filter(status=Payment.Status.PAID, used_at__isnull=True)
            .order_by('paid_at').first())


# --- WayForPay ---------------------------------------------------------------

def _sign(*values):
    message = ';'.join(str(v) for v in values)
    return hmac.new(settings.WAYFORPAY_SECRET_KEY.encode(), message.encode(), hashlib.md5).hexdigest()


def _merchant_domain(request):
    return settings.WAYFORPAY_DOMAIN or urlparse(settings.SITE_URL).hostname or request.get_host()


def _wayforpay_start(request, car):
    amount = price()
    currency = settings.WAYFORPAY_CURRENCY
    reference = f'FIB-{car.pk}-{uuid.uuid4().hex[:10]}'
    order_date = int(time.time())
    product = f'FIBONACCI: {car.make.name} {car.model}'[:255]
    domain = _merchant_domain(request)
    Payment.objects.create(car=car, user=request.user, amount=amount, currency=currency,
                           provider=Payment.Provider.WAYFORPAY, reference=reference)
    fields = {
        'merchantAccount': settings.WAYFORPAY_MERCHANT_ACCOUNT,
        'merchantAuthType': 'SimpleSignature',
        'merchantDomainName': domain,
        'orderReference': reference,
        'orderDate': order_date,
        'amount': f'{amount:.2f}',
        'currency': currency,
        'productName[]': product,
        'productCount[]': 1,
        'productPrice[]': f'{amount:.2f}',
        'clientEmail': request.user.email,
        'language': 'RU' if request.LANGUAGE_CODE == 'ru' else 'EN',
        'returnUrl': request.build_absolute_uri(reverse('wayforpay_return')),
        'serviceUrl': request.build_absolute_uri(reverse('wayforpay_callback')),
    }
    fields['merchantSignature'] = _sign(
        fields['merchantAccount'], domain, reference, order_date, fields['amount'], currency,
        product, 1, fields['amount'])
    return render(request, 'cars/payment_redirect.html', {
        'action': WAYFORPAY_URL, 'fields': fields, 'car': car, 'amount': amount,
        'duration': settings.LISTING_DURATION_DAYS,
    })


def wayforpay_response_valid(data):
    expected = _sign(data.get('merchantAccount', ''), data.get('orderReference', ''),
                     data.get('amount', ''), data.get('currency', ''), data.get('authCode', ''),
                     data.get('cardPan', ''), data.get('transactionStatus', ''),
                     data.get('reasonCode', ''))
    return (data.get('merchantAccount') == settings.WAYFORPAY_MERCHANT_ACCOUNT
            and hmac.compare_digest(expected, str(data.get('merchantSignature', ''))))


def wayforpay_process(data):
    """Handle a WayForPay result (callback or return page). Returns the payment."""
    if not is_configured() or not wayforpay_response_valid(data):
        return None
    payment = Payment.objects.filter(reference=data.get('orderReference', '')).first()
    if payment is None:
        return None
    if Decimal(str(data.get('amount', '0'))) != payment.amount or data.get('currency') != payment.currency:
        return None
    status = data.get('transactionStatus')
    if status == 'Approved':
        return fulfill(payment.reference, paid=True)
    if status in ('Declined', 'Expired', 'Refunded', 'Voided'):
        return fulfill(payment.reference, paid=False)
    return payment  # Pending / InProcessing: wait for the next callback


def wayforpay_answer(order_reference):
    """Reply WayForPay expects from the serviceUrl."""
    now = int(time.time())
    return {'orderReference': order_reference, 'status': 'accept', 'time': now,
            'signature': _sign(order_reference, 'accept', now)}


def parse_callback_body(body):
    """WayForPay posts JSON (sometimes as the only key of a form body)."""
    text = body.decode('utf-8', 'replace').strip()
    try:
        return json.loads(text)
    except ValueError:
        from urllib.parse import parse_qs
        form = parse_qs(text)
        if len(form) == 1:
            try:
                return json.loads(next(iter(form)))
            except ValueError:
                pass
        return {k: v[0] for k, v in form.items()}


# --- Stripe ------------------------------------------------------------------

def _stripe():
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def _stripe_start(request, car):
    amount = price()
    session = _stripe().checkout.Session.create(
        mode='payment',
        customer_email=request.user.email,
        line_items=[{
            'quantity': 1,
            'price_data': {
                'currency': 'eur',
                'unit_amount': int(amount * 100),
                'product_data': {'name': f'FIBONACCI: {car} — {settings.LISTING_DURATION_DAYS} days'},
            },
        }],
        metadata={'car_id': str(car.pk), 'user_id': str(request.user.pk)},
        success_url=request.build_absolute_uri(reverse('cars:payment_success')) + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=request.build_absolute_uri(reverse('cars:my_cars')),
    )
    Payment.objects.create(car=car, user=request.user, amount=amount, currency='EUR',
                           provider=Payment.Provider.STRIPE, reference=session.id)
    return session.url


def stripe_fulfill(session):
    if session.get('payment_status') != 'paid':
        return None  # delayed payment methods: wait for async_payment_succeeded
    return fulfill(session['id'], paid=True)


def retrieve_session(session_id):
    return _stripe().checkout.Session.retrieve(session_id)


def parse_webhook(payload, signature):
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise PaymentsNotConfigured
    return stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
