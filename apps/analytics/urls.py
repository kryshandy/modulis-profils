from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("p/<int:profile_id>.gif", views.pixel, name="pixel"),
    path("a/<int:profile_id>/<slug:kind>", views.click, name="click"),
]
