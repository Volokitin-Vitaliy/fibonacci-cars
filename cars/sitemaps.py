from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Car, Make


class StaticSitemap(Sitemap):
    i18n = True
    alternates = True
    changefreq = 'daily'

    def items(self):
        return ['cars:home', 'cars:list', 'cars:new', 'cars:partnership']

    def location(self, item):
        return reverse(item)


class CategorySitemap(Sitemap):
    """Categories are engine types (petrol, diesel, hybrid, electric, gas)."""
    i18n = True
    alternates = True
    changefreq = 'daily'

    def items(self):
        return list(Car.Fuel.values)

    def location(self, item):
        return reverse('cars:fuel', args=[item])


class MakeSitemap(Sitemap):
    i18n = True
    alternates = True
    changefreq = 'daily'

    def items(self):
        return Make.objects.filter(cars__in=Car.objects.visible()).distinct()


class CarSitemap(Sitemap):
    i18n = True
    alternates = True
    changefreq = 'weekly'

    def items(self):
        return Car.objects.visible().order_by('pk')

    def lastmod(self, car):
        return car.updated_at


sitemaps = {'static': StaticSitemap, 'categories': CategorySitemap, 'makes': MakeSitemap,
            'vehicles': CarSitemap}
