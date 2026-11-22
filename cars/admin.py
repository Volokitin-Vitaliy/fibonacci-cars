from django.contrib import admin

from .models import Car, CarPhoto, Category, Favorite, ImportRun, ListingPeriod, Make


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name_en', 'name_ru', 'slug', 'hollmann_id', 'position')
    list_editable = ('position',)
    prepopulated_fields = {'slug': ('name_en',)}


@admin.register(Make)
class MakeAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}


class CarPhotoInline(admin.TabularInline):
    model = CarPhoto
    extra = 0


class ListingPeriodInline(admin.TabularInline):
    model = ListingPeriod
    extra = 0
    readonly_fields = ('starts_at', 'ends_at', 'amount', 'method', 'created_at')


@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'source', 'price', 'currency', 'status', 'active_until',
                    'is_published', 'owner', 'created_at')
    list_filter = ('source', 'status', 'is_published', 'is_new', 'categories', 'make')
    search_fields = ('model', 'make__name', 'external_id', 'owner__email', 'contact_phone')
    autocomplete_fields = ('make',)
    raw_id_fields = ('owner',)
    filter_horizontal = ('categories',)
    inlines = (CarPhotoInline, ListingPeriodInline)


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ('user', 'car', 'created_at')
    raw_id_fields = ('user', 'car')


@admin.register(ImportRun)
class ImportRunAdmin(admin.ModelAdmin):
    list_display = ('started_at', 'finished_at', 'ok', 'created', 'updated', 'unpublished')
    readonly_fields = [f.name for f in ImportRun._meta.fields]
