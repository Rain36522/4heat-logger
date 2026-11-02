from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import path

from . import views

urlpatterns = [
    path("", views.status, name="status"),
    path("graphes/", views.timeline, name="timeline"),
    path("demarrages/", views.startups, name="startups"),
    path("defauts/", views.faults, name="faults"),
    path("reglages/", views.journal, name="journal"),
    path("reglages/valeur/<str:code>/", views.parameter_info, name="parameter_info"),
    path("assets/plotly.min.js", views.plotly_js, name="plotly_js"),
    path(
        "connexion/",
        login_not_required(auth_views.LoginView.as_view(template_name="registration/login.html")),
        name="login",
    ),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
]
