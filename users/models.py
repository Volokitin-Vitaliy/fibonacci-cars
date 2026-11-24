from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.html import strip_tags
from django.utils.translation import gettext_lazy as _
from django_countries.fields import CountryField


class CustomUserManager(BaseUserManager):
    def create_user(self, email, first_name, last_name, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set.")
        email = self.normalize_email(email)
        user = self.model(email=email, first_name=first_name, last_name=last_name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, first_name, last_name, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, first_name, last_name, password, **extra_fields)


class CustomUser(AbstractUser):
    email = models.EmailField(_('email'), unique=True, max_length=254)
    first_name = models.CharField(_('first name'), max_length=50)
    last_name = models.CharField(_('last name'), max_length=50)
    middle_name = models.CharField(_('middle name'), max_length=50, blank=True)
    country = CountryField(_('country'), blank=True)
    phone = models.CharField(_('phone'), max_length=30, unique=True, null=True, blank=True)
    # Language of the site the user last used; emails are sent in it.
    language = models.CharField(_('language'), max_length=10, choices=settings.LANGUAGES,
                                default='en')
    # Set when the owner clicks the link in the sign-up email (or signs in with Google /
    # Apple, which confirm the address). New sign-ups stay inactive until then.
    email_verified = models.BooleanField(_('email verified'), default=False)

    username = None

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    def __str__(self):
        return self.email

    @property
    def full_name(self):
        return ' '.join(p for p in (self.last_name, self.first_name, self.middle_name) if p)

    @property
    def awaits_verification(self):
        """Signed up with email and password but has not clicked the link yet."""
        return not self.is_active and not self.email_verified

    def clean(self):
        super().clean()
        for field in ('first_name', 'last_name', 'middle_name', 'phone'):
            value = getattr(self, field)
            if value:
                setattr(self, field, strip_tags(value).strip())
