# document_service/management/commands/reindex_documents.py
#
# USAGE:
#   python manage.py reindex_documents              # re-index all failed/pending docs
#   python manage.py reindex_documents --all        # re-index every document
#   python manage.py reindex_documents --id <uuid>  # re-index one specific document
#
# Place this file at:
#   <your_document_app>/management/commands/reindex_documents.py
#
# Make sure the management/commands/ directories have __init__.py files:
#   touch <your_document_app>/management/__init__.py
#   touch <your_document_app>/management/commands/__init__.py

import requests
import os
import time
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Re-trigger indexing for documents stuck in pending/failed state'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Re-index ALL documents, not just failed/pending ones',
        )
        parser.add_argument(
            '--id',
            type=str,
            help='Re-index a specific document by UUID',
        )

    def handle(self, *args, **options):
        # Import here to avoid AppRegistryNotReady errors
        from doc_service.models import Document

        self.stdout.write('=' * 60)
        self.stdout.write('🔄 DOCUMENT RE-INDEXING TOOL')
        self.stdout.write('=' * 60)

        # Build queryset
        if options.get('id'):
            docs = Document.objects.filter(id=options['id'])
            if not docs.exists():
                self.stdout.write(self.style.ERROR(f"❌ Document {options['id']} not found"))
                return
        elif options.get('all'):
            docs = Document.objects.all()
        else:
            # Default: only failed or pending
            docs = Document.objects.filter(
                indexing_status__in=['pending', 'failed']
            )

        total = docs.count()
        self.stdout.write(f'📄 Found {total} document(s) to re-index\n')

        if total == 0:
            self.stdout.write(self.style.SUCCESS('✅ Nothing to re-index'))
            return

        chatbot_url = getattr(settings, 'CHATBOT_SERVICE_URL', 'http://127.0.0.1:8002')
        webhook_url = f"{chatbot_url}/api/chat/webhooks/index-document/"
        webhook_api_key = getattr(settings, 'WEBHOOK_API_KEY', 'webhook-secret-key-12345')

        headers = {
            "X-API-Key": webhook_api_key,
            "Content-Type": "application/json"
        }

        success_count = 0
        fail_count = 0

        for doc in docs:
            self.stdout.write(f'\n📎 Processing: {doc.title or doc.file_name}')
            self.stdout.write(f'   ID:     {doc.id}')
            self.stdout.write(f'   Status: {doc.indexing_status}')

            # Get absolute file path
            try:
                if hasattr(doc.file, 'path'):
                    file_path = os.path.abspath(doc.file.path)
                else:
                    file_path = str(doc.file)

                if not os.path.exists(file_path):
                    self.stdout.write(self.style.ERROR(f'   ❌ File not found on disk: {file_path}'))
                    fail_count += 1
                    continue

                self.stdout.write(f'   Path:   {file_path}')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'   ❌ Cannot get file path: {e}'))
                fail_count += 1
                continue

            # Build webhook payload — must match DocumentIndexWebhookView expectations
            tenant_id = str(doc.tenant_id) if doc.tenant_id else str(doc.uploaded_by_id)
            payload = {
                "document_id": str(doc.id),
                "tenant_id": tenant_id,
                "user_id": str(doc.uploaded_by_id),
                "file_path": file_path,
                "file_type": doc.file_type or 'application/pdf',
                "title": doc.title or doc.file_name,
                "file_name": doc.file_name,
                "file_size": doc.file_size,
            }

            # Reset status to pending before sending
            doc.indexing_status = 'pending'
            doc.save(update_fields=['indexing_status', 'updated_at'])

            try:
                response = requests.post(
                    webhook_url,
                    json=payload,
                    headers=headers,
                    timeout=120  # indexing can take a while
                )

                if response.status_code in [200, 201, 202]:
                    self.stdout.write(self.style.SUCCESS(
                        f'   ✅ Queued for indexing successfully'
                    ))
                    success_count += 1
                else:
                    doc.indexing_status = 'failed'
                    doc.save(update_fields=['indexing_status', 'updated_at'])
                    self.stdout.write(self.style.ERROR(
                        f'   ❌ Webhook returned {response.status_code}: {response.text[:200]}'
                    ))
                    fail_count += 1

            except requests.exceptions.ConnectionError:
                doc.indexing_status = 'failed'
                doc.save(update_fields=['indexing_status', 'updated_at'])
                self.stdout.write(self.style.ERROR(
                    f'   ❌ Cannot connect to chat service at {chatbot_url}\n'
                    f'      Make sure the AI Chat service is running on port 8002'
                ))
                fail_count += 1
                break  # No point continuing if service is down

            except requests.exceptions.Timeout:
                doc.indexing_status = 'failed'
                doc.save(update_fields=['indexing_status', 'updated_at'])
                self.stdout.write(self.style.ERROR('   ❌ Request timed out (>120s)'))
                fail_count += 1

            except Exception as e:
                doc.indexing_status = 'failed'
                doc.save(update_fields=['indexing_status', 'updated_at'])
                self.stdout.write(self.style.ERROR(f'   ❌ Unexpected error: {e}'))
                fail_count += 1

            # Small delay between documents to avoid overwhelming the service
            if total > 1:
                time.sleep(0.5)

        self.stdout.write('\n' + '=' * 60)
        self.stdout.write(f'✅ Success: {success_count}   ❌ Failed: {fail_count}')
        self.stdout.write('=' * 60)