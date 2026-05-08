from django.apps import AppConfig


class ShopConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'shop'
    verbose_name = 'Sewing Shop'

    def ready(self):
        # Compatibility shim: Django 4.2's BaseContext.__copy__ uses
        # ``copy(super())`` which raises ``AttributeError: 'super' object has
        # no attribute 'dicts'`` on Python 3.14 because the ``super`` proxy
        # is no longer copy-compatible.  We replace it with a copy
        # implementation that doesn't go through ``super``.
        try:
            import sys
            if sys.version_info >= (3, 14):
                from django.template.context import BaseContext

                def _safe_copy(self):
                    duplicate = type(self).__new__(type(self))
                    duplicate.__dict__.update(self.__dict__)
                    duplicate.dicts = self.dicts[:]
                    return duplicate

                BaseContext.__copy__ = _safe_copy
        except Exception:
            pass
