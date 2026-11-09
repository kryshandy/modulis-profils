from django.apps import AppConfig


class ProfilesConfig(AppConfig):
    name = "apps.profiles"
    verbose_name = "Profils (pages pros)"

    def ready(self) -> None:
        from . import signals

        signals.connect_post_migrate(self)
