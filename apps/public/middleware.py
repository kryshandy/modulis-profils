"""Settings entry point: "apps.public.middleware.PublicHeadersMiddleware" (before LocaleMiddleware)."""

from .http import PublicHeadersMiddleware

__all__ = ["PublicHeadersMiddleware"]
