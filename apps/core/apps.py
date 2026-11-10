from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    verbose_name = "Référentiels (pays, villes, métiers)"

    def ready(self) -> None:
        from . import signals  # noqa: F401  (registers the staff short-session receiver)
