from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from . import services
from .models import Car, CarPhoto, Category, Favorite, ImportRun, ListingPeriod, Make, Payment


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


class ModerationFilter(admin.SimpleListFilter):
    title = _('moderation')
    parameter_name = 'moderation'

    def lookups(self, request, model_admin):
        return Car.Moderation.choices

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(source=Car.Source.USER, moderation=self.value())
        return queryset


@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'source', 'moderation', 'price', 'currency', 'status',
                    'active_until', 'is_published', 'owner', 'created_at')
    list_filter = (ModerationFilter, 'source', 'status', 'is_published', 'is_new',
                   'categories', 'make')
    search_fields = ('model', 'make__name', 'external_id', 'owner__email', 'contact_phone')
    autocomplete_fields = ('make',)
    raw_id_fields = ('owner',)
    filter_horizontal = ('categories',)
    inlines = (CarPhotoInline, ListingPeriodInline)
    actions = ('approve_selected', 'reject_selected')

    def save_model(self, request, obj, form, change):
        # Changing "moderation" in the form goes through the same steps as the
        # list actions: the first month starts and the owner gets an email.
        moderation_changed = change and 'moderation' in form.changed_data
        new_state = obj.moderation
        if moderation_changed and obj.source == Car.Source.USER:
            obj.moderation = form.initial.get('moderation')
        super().save_model(request, obj, form, change)
        if moderation_changed and obj.source == Car.Source.USER:
            if new_state == Car.Moderation.APPROVED:
                services.approve(obj)
            elif new_state == Car.Moderation.REJECTED:
                services.reject(obj, obj.rejection_reason)
            else:
                obj.moderation = new_state
                obj.save(update_fields=['moderation'])

    @admin.action(description=_('Approve selected listings'))
    def approve_selected(self, request, queryset):
        count = 0
        for car in queryset.filter(source=Car.Source.USER).exclude(moderation=Car.Moderation.APPROVED):
            services.approve(car)
            count += 1
        self.message_user(request, _('Approved: %(n)s') % {'n': count}, messages.SUCCESS)

    @admin.action(description=_('Reject selected listings'))
    def reject_selected(self, request, queryset):
        count = 0
        for car in queryset.filter(source=Car.Source.USER).exclude(moderation=Car.Moderation.REJECTED):
            services.reject(car)
            count += 1
        self.message_user(
            request,
            _('Rejected: %(n)s. To give a reason, open the listing and fill in "rejection reason".')
            % {'n': count}, messages.WARNING)


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ('user', 'car', 'created_at')
    raw_id_fields = ('user', 'car')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'car', 'user', 'amount', 'currency', 'status', 'paid_at')
    list_filter = ('status',)
    search_fields = ('stripe_session_id', 'user__email')
    readonly_fields = [f.name for f in Payment._meta.fields]


@admin.register(ImportRun)
class ImportRunAdmin(admin.ModelAdmin):
    list_display = ('started_at', 'finished_at', 'ok', 'created', 'updated', 'unpublished')
    readonly_fields = [f.name for f in ImportRun._meta.fields]
