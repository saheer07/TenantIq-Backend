"""
RAG Vector Store Module
Handles vector storage and retrieval using ChromaDB
"""

import os
from typing import List, Dict, Optional, Tuple
import chromadb
from chromadb.config import Settings
from django.conf import settings
import uuid


import logging

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Manages vector storage using ChromaDB with multi-tenant support
    """
    
    def __init__(self, persist_directory: Optional[str] = None):
        """
        Initialize vector store
        
        Args:
            persist_directory: Directory to persist ChromaDB data
        """
        if persist_directory is None:
            persist_directory = os.path.join(settings.BASE_DIR, 'chromadb_data')
        
        # Ensure directory exists
        os.makedirs(persist_directory, exist_ok=True)
        
        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        self.persist_directory = persist_directory
        logger.info(f"[VECTOR_STORE] Initialized at: {persist_directory}")
    
    def _normalise_tenant_id(self, tenant_id: str) -> str:
        """Normalize tenant ID to a consistent format for collection names"""
        return str(tenant_id).strip().lower()

    def get_or_create_collection(self, tenant_id: str) -> chromadb.Collection:
        """
        Get or create a collection for a specific tenant
        
        Args:
            tenant_id: Unique tenant identifier
            
        Returns:
            ChromaDB collection for the tenant
        """
        normalised_id = self._normalise_tenant_id(tenant_id)
        collection_name = f"tenant_{normalised_id}"
        logger.info(f"[VECTOR_STORE] Accessing collection: {collection_name}")
        
        try:
            collection = self.client.get_collection(name=collection_name)
        except Exception:
            logger.info(f"[VECTOR_STORE] Creating new collection: {collection_name}")
            collection = self.client.create_collection(
                name=collection_name,
                metadata={"tenant_id": normalised_id}
            )
        
        return collection
    
    def _sanitize_metadatas(self, metadatas: List[Dict]) -> List[Dict]:
        """
        Sanitize metadata values for ChromaDB compatibility.
        ChromaDB only accepts str, int, float, bool, or None.
        """
        import json
        sanitized_list = []
        for metadata in metadatas:
            sanitized = {}
            for key, value in metadata.items():
                if value is None or isinstance(value, (str, int, float, bool)):
                    sanitized[key] = value
                elif isinstance(value, list):
                    sanitized[key] = ", ".join(str(v) for v in value) if value else ""
                elif isinstance(value, dict):
                    sanitized[key] = json.dumps(value)
                else:
                    sanitized[key] = str(value)
            sanitized_list.append(sanitized)
        return sanitized_list

    def add_documents(
        self,
        tenant_id: str,
        documents: List[str],
        embeddings: List[List[float]],
        metadatas: List[Dict],
        document_id: str
    ) -> List[str]:
        """
        Add documents to the vector store
        
        Args:
            tenant_id: Tenant identifier
            documents: List of document texts
            embeddings: List of embedding vectors
            metadatas: List of metadata dictionaries
            document_id: Source document ID
            
        Returns:
            List of generated chunk IDs
        """
        if not (len(documents) == len(embeddings) == len(metadatas)):
            raise ValueError("Documents, embeddings, and metadatas must have the same length")
        
        collection = self.get_or_create_collection(tenant_id)
        
        # Inject document_id and status into each metadata dict for reliable deletion and filtering
        for meta in metadatas:
            meta['document_id'] = str(document_id)
            meta['indexing_status'] = 'indexed'

        # Last-line-of-defense sanitization
        metadatas = self._sanitize_metadatas(metadatas)
        
        # Generate unique IDs for each chunk
        chunk_ids = [f"{document_id}_chunk_{i}" for i in range(len(documents))]
        
        # Add to collection
        collection.add(
            ids=chunk_ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas
        )
        
        return chunk_ids
    
    def query(
        self,
        tenant_id: str,
        query_embedding: List[float],
        n_results: int = 5,
        filter_metadata: Optional[Dict] = None
    ) -> Dict:
        """
        Query the vector store for similar documents
        
        Args:
            tenant_id: Tenant identifier
            query_embedding: Query embedding vector
            n_results: Number of results to return
            filter_metadata: Optional metadata filters
            
        Returns:
            Dictionary with query results
        """
        collection = self.get_or_create_collection(tenant_id)
        
        # Perform query
        query_kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"]
        }
        
        if filter_metadata and isinstance(filter_metadata, dict):
            query_kwargs["where"] = filter_metadata
            
        logger.info(f"[VECTOR_STORE] Querying collection '{collection.name}' for tenant '{tenant_id}' with filters: {filter_metadata}")
        results = collection.query(**query_kwargs)
        
        # Format results
        formatted_results = {
            'documents': results['documents'][0] if results['documents'] else [],
            'metadatas': results['metadatas'][0] if results['metadatas'] else [],
            'distances': results['distances'][0] if results['distances'] else [],
            'count': len(results['documents'][0]) if results['documents'] else 0
        }
        
        return formatted_results
    
    def delete_document(self, tenant_id: str, document_id: str) -> int:
        """
        Delete all chunks associated with a document
        
        Args:
            tenant_id: Tenant identifier
            document_id: Document identifier
            
        Returns:
            Number of chunks deleted
        """
        collection = self.get_or_create_collection(tenant_id)
        
        # Query for all chunks with this document_id
        try:
            results = collection.get(
                where={"document_id": document_id}
            )
            
            if results['ids']:
                collection.delete(ids=results['ids'])
                return len(results['ids'])
            
            return 0
            
        except Exception as e:
            print(f"Error deleting document: {str(e)}")
            return 0
    
    def update_document(
        self,
        tenant_id: str,
        document_id: str,
        documents: List[str],
        embeddings: List[List[float]],
        metadatas: List[Dict]
    ) -> List[str]:
        """
        Update a document by deleting old chunks and adding new ones
        
        Args:
            tenant_id: Tenant identifier
            document_id: Document identifier
            documents: New document texts
            embeddings: New embedding vectors
            metadatas: New metadata dictionaries
            
        Returns:
            List of new chunk IDs
        """
        # Delete existing chunks
        self.delete_document(tenant_id, document_id)
        
        # Add new chunks
        return self.add_documents(tenant_id, documents, embeddings, metadatas, document_id)
    
    def get_document_count(self, tenant_id: str, document_id: Optional[str] = None) -> int:
        """
        Get count of chunks in the collection
        
        Args:
            tenant_id: Tenant identifier
            document_id: Optional document identifier to count chunks for specific document
            
        Returns:
            Number of chunks
        """
        collection = self.get_or_create_collection(tenant_id)
        
        if document_id:
            results = collection.get(where={"document_id": document_id})
            return len(results['ids']) if results['ids'] else 0
        else:
            return collection.count()
    
    def get_all_document_ids(self, tenant_id: str) -> List[str]:
        """
        Get all unique document IDs in the collection
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            List of document IDs
        """
        collection = self.get_or_create_collection(tenant_id)
        
        try:
            results = collection.get()
            
            if results['metadatas']:
                document_ids = set()
                for metadata in results['metadatas']:
                    if 'document_id' in metadata:
                        document_ids.add(metadata['document_id'])
                
                return list(document_ids)
            
            return []
            
        except Exception as e:
            print(f"Error getting document IDs: {str(e)}")
            return []
    
    def clear_collection(self, tenant_id: str) -> bool:
        """
        Clear all data from a tenant's collection
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            True if successful, False otherwise
        """
        try:
            normalised_id = self._normalise_tenant_id(tenant_id)
            collection_name = f"tenant_{normalised_id}"
            self.client.delete_collection(name=collection_name)
            return True
        except Exception as e:
            print(f"Error clearing collection: {str(e)}")
            return False
    
    def get_stats(self, tenant_id: Optional[str] = None) -> Dict:
        """
        Get statistics about the vector store
        
        Args:
            tenant_id: Optional tenant identifier
            
        Returns:
            Dictionary with statistics
        """
        if tenant_id:
            collection = self.get_or_create_collection(tenant_id)
            return {
                'tenant_id': tenant_id,
                'total_chunks': collection.count(),
                'unique_documents': len(self.get_all_document_ids(tenant_id))
            }
        else:
            # Get stats for all collections
            collections = self.client.list_collections()
            return {
                'total_collections': len(collections),
                'collections': [
                    {
                        'name': col.name,
                        'count': col.count()
                    }
                    for col in collections
                ]
            }
    
    def peek(self, tenant_id: str, limit: int = 10) -> Dict:
        """
        Peek at some documents in the collection
        
        Args:
            tenant_id: Tenant identifier
            limit: Number of documents to return
            
        Returns:
            Dictionary with sample documents
        """
        collection = self.get_or_create_collection(tenant_id)
        
        try:
            results = collection.peek(limit=limit)
            return {
                'ids': results['ids'],
                'documents': results['documents'],
                'metadatas': results['metadatas']
            }
        except Exception as e:
            print(f"Error peeking collection: {str(e)}")
            return {'ids': [], 'documents': [], 'metadatas': []}


# Utility functions

def calculate_relevance_score(distance: float) -> float:
    """
    Convert distance to relevance score (0-1, higher is better)
    
    Args:
        distance: Distance from ChromaDB (lower is better)
        
    Returns:
        Relevance score
    """
    # ChromaDB uses L2 distance by default
    # Convert to similarity score (0-1)
    return 1 / (1 + distance)


def filter_results_by_threshold(
    results: Dict, 
    threshold: float = 0.5
) -> Dict:
    """
    Filter query results by relevance threshold
    
    Args:
        results: Results from query
        threshold: Minimum relevance score (0-1)
        
    Returns:
        Filtered results
    """
    filtered_documents = []
    filtered_metadatas = []
    filtered_distances = []
    
    for doc, meta, dist in zip(
        results['documents'],
        results['metadatas'],
        results['distances']
    ):
        relevance = calculate_relevance_score(dist)
        if relevance >= threshold:
            filtered_documents.append(doc)
            filtered_metadatas.append(meta)
            filtered_distances.append(dist)
    
    return {
        'documents': filtered_documents,
        'metadatas': filtered_metadatas,
        'distances': filtered_distances,
        'count': len(filtered_documents)
    }