import os
import django
import sys

# Add project root to path so we can import apps
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'document_service.settings')
django.setup()

from doc_service.models import Document

stuck_docs = Document.objects.filter(indexing_status__in=['pending', 'processing'])
count = stuck_docs.count()
stuck_docs.update(indexing_status='failed')
print(f"Updated {count} documents to failed status.")
