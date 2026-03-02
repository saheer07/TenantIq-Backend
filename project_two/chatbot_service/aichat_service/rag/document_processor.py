"""
RAG Document Processor
Handles document parsing, chunking, and preprocessing for various file formats
"""

import os
import re
from typing import List, Dict, Optional
from dataclasses import dataclass
import tiktoken
from docx import Document
from PyPDF2 import PdfReader


@dataclass
class DocumentChunk:
    """Represents a chunk of text from a document"""
    content: str
    metadata: Dict
    chunk_index: int
    token_count: int


class DocumentProcessor:
    """
    Processes documents and splits them into chunks for embedding
    """
    
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        """
        Initialize document processor
        
        Args:
            chunk_size: Maximum tokens per chunk
            chunk_overlap: Number of overlapping tokens between chunks
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
    
    def process_document(
        self, 
        file_path: str, 
        document_id: str,
        metadata: Optional[Dict] = None
    ) -> List[DocumentChunk]:
        """
        Process a document and return chunks
        
        Args:
            file_path: Path to the document file
            document_id: Unique identifier for the document
            metadata: Additional metadata to attach to chunks
            
        Returns:
            List of DocumentChunk objects
        """
        # Extract text based on file type
        file_extension = os.path.splitext(file_path)[1].lower()
        
        if file_extension == '.pdf':
            text = self._extract_pdf_text(file_path)
        elif file_extension == '.docx':
            text = self._extract_docx_text(file_path)
        elif file_extension == '.txt':
            text = self._extract_txt_text(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_extension}")
        
        # Clean the text
        text = self._clean_text(text)
        
        # Split into chunks
        chunks = self._create_chunks(text, document_id, metadata or {})
        
        return chunks
    
    def _extract_pdf_text(self, file_path: str) -> str:
        """Extract text from PDF file"""
        text = ""
        try:
            reader = PdfReader(file_path)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        except Exception as e:
            raise ValueError(f"Error reading PDF: {str(e)}")
        
        return text
    
    def _extract_docx_text(self, file_path: str) -> str:
        """Extract text from DOCX file"""
        text = ""
        try:
            doc = Document(file_path)
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
        except Exception as e:
            raise ValueError(f"Error reading DOCX: {str(e)}")
        
        return text
    
    def _extract_txt_text(self, file_path: str) -> str:
        """Extract text from TXT file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
        except UnicodeDecodeError:
            # Try with different encoding
            with open(file_path, 'r', encoding='latin-1') as f:
                text = f.read()
        except Exception as e:
            raise ValueError(f"Error reading TXT: {str(e)}")
        
        return text
    
    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        # Replace various line endings with \n
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # Remove excessive whitespace but keep printable characters
        # This collapses multiple spaces into one, and multiple newlines into one
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n+', '\n', text)
        
        return text.strip()
    
    def _create_chunks(
        self, 
        text: str, 
        document_id: str, 
        metadata: Dict
    ) -> List[DocumentChunk]:
        """
        Split text into overlapping chunks based on token count
        
        Args:
            text: The text to chunk
            document_id: Unique identifier for the document
            metadata: Metadata to attach to each chunk
            
        Returns:
            List of DocumentChunk objects
        """
        # Encode the entire text
        tokens = self.encoding.encode(text)
        
        chunks = []
        chunk_index = 0
        
        start = 0
        while start < len(tokens):
            # Calculate end position
            end = start + self.chunk_size
            
            # Get chunk tokens
            chunk_tokens = tokens[start:end]
            
            # Decode back to text
            chunk_text = self.encoding.decode(chunk_tokens)
            
            # Create chunk metadata
            chunk_metadata = {
                **metadata,
                'document_id': document_id,
                'chunk_index': chunk_index,
                'start_char': start,
                'end_char': end
            }
            
            # Create chunk object
            chunk = DocumentChunk(
                content=chunk_text,
                metadata=chunk_metadata,
                chunk_index=chunk_index,
                token_count=len(chunk_tokens)
            )
            
            chunks.append(chunk)
            
            # Move to next chunk with overlap
            start = end - self.chunk_overlap
            chunk_index += 1
        
        return chunks
    
    def count_tokens(self, text: str) -> int:
        """Count the number of tokens in text"""
        return len(self.encoding.encode(text))
    
    def estimate_chunks(self, file_path: str) -> int:
        """Estimate number of chunks a document will produce"""
        file_extension = os.path.splitext(file_path)[1].lower()
        
        if file_extension == '.pdf':
            text = self._extract_pdf_text(file_path)
        elif file_extension == '.docx':
            text = self._extract_docx_text(file_path)
        elif file_extension == '.txt':
            text = self._extract_txt_text(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_extension}")
        
        token_count = self.count_tokens(text)
        
        # Calculate approximate chunks
        estimated_chunks = max(1, (token_count - self.chunk_overlap) // (self.chunk_size - self.chunk_overlap))
        
        return estimated_chunks


# Utility functions

def validate_document_size(file_path: str, max_size_mb: int = 10) -> bool:
    """
    Validate document file size
    
    Args:
        file_path: Path to the document
        max_size_mb: Maximum file size in MB
        
    Returns:
        True if valid, False otherwise
    """
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    return file_size_mb <= max_size_mb


def get_document_info(file_path: str) -> Dict:
    """
    Get basic information about a document
    
    Args:
        file_path: Path to the document
        
    Returns:
        Dictionary with document information
    """
    file_stats = os.stat(file_path)
    file_extension = os.path.splitext(file_path)[1].lower()
    
    return {
        'file_name': os.path.basename(file_path),
        'file_type': file_extension,
        'file_size': file_stats.st_size,
        'file_size_mb': round(file_stats.st_size / (1024 * 1024), 2)
    }