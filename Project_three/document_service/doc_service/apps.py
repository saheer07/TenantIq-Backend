from django.apps import AppConfig


class DocServiceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'doc_service'

    def ready(self):
        """Import signals when Django starts"""
        import doc_service.signals