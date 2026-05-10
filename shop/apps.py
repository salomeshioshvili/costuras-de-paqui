from django.apps import AppConfig


class ShopConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'shop'
    verbose_name = 'Costuras de Paqui'

    def ready(self):
        # Wire event subscribers (registers @events.on handlers).
        from shop.services import communications  # noqa: F401
