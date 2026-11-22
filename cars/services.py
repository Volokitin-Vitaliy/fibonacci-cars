from django.utils import timezone

from .models import Car


def expire_listings():
    """Mark user listings whose month is over as inactive.

    Visibility does not depend on this job (see CarQuerySet.visible), it only
    keeps the stored status in sync and returns how many listings expired."""
    return (Car.objects
            .filter(source=Car.Source.USER, status=Car.Status.ACTIVE,
                    active_until__lte=timezone.now())
            .update(status=Car.Status.INACTIVE))
