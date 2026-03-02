from django.apps import AppConfig


class AichatServiceConfig(AppConfig):
    name = 'aichat_service'

    def ready(self):
        import aichat_service.signals
