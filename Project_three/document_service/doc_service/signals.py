from django.db.models.signals import pre_save
from django.dispatch import receiver
from .models import Document


@receiver(pre_save, sender=Document)
def populate_file_metadata(sender, instance, **kwargs):
 
    if instance.file:
        # Only populate if fields are empty or None
        if not instance.file_name:
            instance.file_name = instance.file.name
            print(f"✅ Auto-populated file_name: {instance.file_name}")
        
        if not instance.file_size or instance.file_size == 0:
            instance.file_size = instance.file.size
            print(f"✅ Auto-populated file_size: {instance.file_size}")
        
        if not instance.file_type:
            # Try to get content type from file
            content_type = getattr(instance.file.file, 'content_type', None) if hasattr(instance.file, 'file') else None
            instance.file_type = content_type or 'application/octet-stream'
            print(f"✅ Auto-populated file_type: {instance.file_type}")