from django.db import migrations


def record_verified_emails(apps, schema_editor):
    """Active accounts are confirmed (our link, Google / Apple, or made by an admin):
    mark them so and give allauth a verified email record for each."""
    User = apps.get_model('users', 'CustomUser')
    EmailAddress = apps.get_model('account', 'EmailAddress')
    User.objects.filter(is_active=True).update(email_verified=True)
    for user in User.objects.filter(email_verified=True).exclude(email=''):
        email = user.email.lower()
        address = EmailAddress.objects.filter(user=user, email__iexact=email).first()
        if address is None:
            EmailAddress.objects.filter(user=user).update(primary=False)
            EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
        elif not address.verified or not address.primary:
            address.verified = address.primary = True
            address.save()


class Migration(migrations.Migration):
    dependencies = [
        ('users', '0005_email_verified'),
        ('account', '0009_emailaddress_unique_primary_email'),
    ]

    operations = [migrations.RunPython(record_verified_emails, migrations.RunPython.noop)]
