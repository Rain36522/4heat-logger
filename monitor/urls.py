from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import path

from . import views

urlpatterns = [
    path("", views.status, name="status"),
    path("graphes/", views.timeline, name="timeline"),
    path("graphes/export.csv", views.timeline_export, name="timeline_export"),
    path("demarrages/", views.startups, name="startups"),
    path("comparer/", views.compare_days, name="compare_days"),
    path("defauts/", views.faults, name="faults"),
    path("reglages/", views.journal, name="journal"),
    path("reglages/valeur/<str:code>/", views.parameter_info, name="parameter_info"),
    path("parametres/", views.parameters, name="parameters"),
    path("parametres/export.csv", views.parameters_export, name="parameters_export"),
    path("parametres/historique.csv", views.changes_export, name="changes_export"),
    path("cycle/", views.boiler_cycle, name="boiler_cycle"),
    path("pilotage/", views.control_page, name="control"),
    path("pilotage/marche/", views.control_power, {"action": "on"}, name="control_on"),
    path("pilotage/arret/", views.control_power, {"action": "off"}, name="control_off"),
    path("pilotage/consigne/", views.control_target, name="control_target"),
    path("pilotage/horloge/", views.clock_toggle, name="clock_toggle"),
    path("pilotage/plages/", views.slot_add, name="slot_add"),
    path("pilotage/plages/<int:pk>/supprimer/", views.slot_delete, name="slot_delete"),
    path("pilotage/conges/", views.day_off_add, name="day_off_add"),
    path("pilotage/conges/<int:pk>/supprimer/", views.day_off_delete, name="day_off_delete"),
    path("assets/plotly.min.js", views.plotly_js, name="plotly_js"),
    path(
        "connexion/",
        login_not_required(auth_views.LoginView.as_view(template_name="registration/login.html")),
        name="login",
    ),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
]
