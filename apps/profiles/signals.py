"""Keep the slug registry in sync with trades and cities (review item #6)."""

from django.db.models.signals import post_migrate, post_save
from django.dispatch import receiver

from apps.core.models import City, Trade

from . import services


@receiver(post_save, sender=Trade)
def reserve_trade_slugs(sender, instance: Trade, **kwargs):
    services.reserve_slug(instance.slug, "trade")
    services.reserve_slug(instance.plural_slug, "trade")


@receiver(post_save, sender=City)
def reserve_city_slug(sender, instance: City, **kwargs):
    services.reserve_slug(instance.slug, "city")


def sync_after_migrate(sender, **kwargs):
    services.sync_reserved_slugs()


def connect_post_migrate(app_config):
    post_migrate.connect(sync_after_migrate, sender=app_config, dispatch_uid="profiles_sync_reserved_slugs")
