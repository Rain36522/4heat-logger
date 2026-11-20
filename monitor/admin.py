from django.contrib import admin

from .models import CodeLabel, CommandLog, DayOff, Parameter, ScheduleSlot, SettingChange

admin.site.site_header = "Chauffage — administration"
admin.site.site_title = "Chauffage"
admin.site.index_title = "Journal de réglages et légendes"


@admin.register(Parameter)
class ParameterAdmin(admin.ModelAdmin):
    list_display = ("code", "section", "description", "unit", "state_label", "baseline_value", "current")
    list_filter = ("section", "family")
    search_fields = ("code", "section", "description")  # also used by the autocomplete of changes
    list_per_page = 100

    @admin.display(description="valeur actuelle")
    def current(self, parameter):
        return parameter.current_value


@admin.register(SettingChange)
class SettingChangeAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "time_is_approximate", "parameter", "old_value", "new_value", "comment")
    list_filter = ("time_is_approximate", "parameter__section")
    search_fields = ("parameter__code", "parameter__description", "comment")
    autocomplete_fields = ("parameter",)
    date_hierarchy = "timestamp"
    list_select_related = ("parameter",)
    # Leave "ancienne valeur" empty: it is filled in with the value the parameter had before.


@admin.register(CodeLabel)
class CodeLabelAdmin(admin.ModelAdmin):
    list_display = ("kind", "code", "name")
    list_filter = ("kind",)


admin.site.register(ScheduleSlot)


@admin.register(DayOff)
class DayOffAdmin(admin.ModelAdmin):
    list_display = ("first_day", "last_day", "label")
    date_hierarchy = "first_day"


@admin.register(CommandLog)
class CommandLogAdmin(admin.ModelAdmin):
    """Read-only: the log is the record of what was really sent."""

    list_display = ("timestamp", "source", "action", "value", "status", "attempts", "finished_at", "detail")
    list_filter = ("status", "source", "action")
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
