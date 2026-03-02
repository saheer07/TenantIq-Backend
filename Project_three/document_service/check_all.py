import os
import django
import sys

# Add project root to path so we can import apps
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'document_service.settings')
django.setup()

from doc_service.models import Document

docs = Document.objects.all()
print(f"Total documents: {docs.count()}")
for d in docs:
    print(f"- ID: {d.id}, Tenant: {d.tenant_id}, Status: {d.indexing_status}")
