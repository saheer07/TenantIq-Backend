"""
RAG Retriever Module
Uses Groq (FREE) instead of OpenAI for chat completions.
Handles retrieval and response generation with LLM.

FIXES APPLIED:
  FIX-4 (indirect): retrieve() no longer passes filter_metadata to vector_store.query()
         unless the caller explicitly provides one — the vector_store.query() fix handles
         the `where=None` problem, but this layer is cleaner about it too.
  FIX-7: query_and_respond() — relevance_scores are now computed inside the method from
         the distances list so the zip is always over lists of the same length. The
         previous code appended 'relevance_scores' to the results dict but the zip
         iterated over retrieval_results['relevance_scores'] which is a flat list only
         when retrieve() adds it *after* the call — this is now explicit and safe.
  FIX-8: context building respects MAX_CONTEXT_CHARS (now set to 12000 in views.py) so
         all retrieved chunks actually make it into the LLM prompt.
"""

from typing import List, Dict, Optional
from django.conf import settings
from .embeddings import EmbeddingGenerator
from .vector_store import VectorStore, calculate_relevance_score
import logging

logger = logging.getLogger(__name__)

STRICT_FALLBACK_MESSAGE = (
    "The requested information is not available in the uploaded document."
)


# ──────────────────────────────────────────────────────────────────────────────
# AI client helpers
# ──────────────────────────────────────────────────────────────────────────────

def get_ai_client():
    """Return the appropriate AI client based on the AI_PROVIDER setting."""
    provider = getattr(settings, "AI_PROVIDER", "groq")

    if provider == "groq":
        try:
            from groq import Groq
            api_key = getattr(settings, "GROQ_API_KEY", "")
            if not api_key or api_key == "PASTE_YOUR_GROQ_KEY_HERE":
                raise ValueError(
                    "GROQ_API_KEY is not set. Get your free key at https://console.groq.com"
                )
            logger.info("Using Groq AI provider (FREE)")
            return Groq(api_key=api_key), provider
        except ImportError:
            raise ImportError("groq package not installed. Run: pip install groq")

    elif provider == "openai":
        from openai import OpenAI
        api_key = getattr(settings, "OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set.")
        logger.info("Using OpenAI provider")
        return OpenAI(api_key=api_key), provider

    else:
        raise ValueError(f"Unknown AI_PROVIDER: {provider}. Use 'groq' or 'openai'.")


def get_model_name() -> str:
    """Return the correct model name for the current provider."""
    provider = getattr(settings, "AI_PROVIDER", "groq")
    if provider == "groq":
        return getattr(settings, "GROQ_MODEL", "llama3-8b-8192")
    return getattr(settings, "OPENAI_MODEL", "gpt-3.5-turbo")


# ──────────────────────────────────────────────────────────────────────────────
# RAGRetriever
# ──────────────────────────────────────────────────────────────────────────────

class RAGRetriever:
    """
    Retrieves relevant document chunks and generates responses using an LLM.
    Supports Groq (free) and OpenAI providers.
    """

    def __init__(
        self,
        embedding_generator: Optional[EmbeddingGenerator] = None,
        vector_store: Optional[VectorStore] = None,
        llm_model: str = None,
    ):
        self.embedding_generator = embedding_generator or EmbeddingGenerator()
        self.vector_store = vector_store or VectorStore()
        self.llm_model = llm_model or get_model_name()

        # A low threshold (0.1) ensures documents are not filtered out
        # because of mild phrasing differences between query and content.
        self.relevance_threshold = float(
            getattr(settings, "DEFAULT_RELEVANCE_THRESHOLD", 0.1)
        )
        # Maximum total characters sent to the LLM as context.
        # 12 000 chars ≈ 6 × 500-token chunks, enough for a full resume.
        self.max_context_chars = int(
            getattr(settings, "MAX_CONTEXT_CHARS", 12_000)
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Retrieval
    # ──────────────────────────────────────────────────────────────────────────

    def retrieve(
        self,
        tenant_id: str,
        query: str,
        n_results: int = 5,
        filter_metadata: Optional[Dict] = None,
    ) -> Dict:
        """
        Embed the query and fetch the top-n_results chunks from ChromaDB.

        Returns a dict with keys: documents, metadatas, distances, count,
        and relevance_scores (derived from distances).
        """
        query_embedding = self.embedding_generator.generate_embedding(query)

        raw = self.vector_store.query(
            tenant_id=tenant_id,
            query_embedding=query_embedding,
            n_results=n_results,
            # FIX-4 (indirect): only pass filter when it is a non-empty dict
            filter_metadata=filter_metadata if filter_metadata else None,
        )

        # Compute relevance scores from the flat distances list
        raw["relevance_scores"] = [
            calculate_relevance_score(d) for d in raw["distances"]
        ]

        num_found = raw["count"]
        logger.info(
            f"[RETRIEVER] Query='{query[:60]}...' → {num_found} chunks retrieved "
            f"(requested {n_results})"
        )
        if num_found > 0:
            logger.debug(
                f"[RETRIEVER] Scores: {[round(s, 3) for s in raw['relevance_scores']]}"
            )
        else:
            logger.warning(
                "[RETRIEVER] Zero chunks returned — check that documents are "
                "indexed for this tenant_id and that the embedding model matches."
            )

        return raw

    # ──────────────────────────────────────────────────────────────────────────
    # Generation
    # ──────────────────────────────────────────────────────────────────────────

    def generate_response(
        self,
        query: str,
        context_documents: List[str],
        conversation_history: Optional[List[Dict]] = None,
        max_tokens: int = 800,
    ) -> Dict:
        """Generate a response using the retrieved chunks as context."""
        context = self._build_context(context_documents)
        system_prompt = self._build_system_prompt(context)

        messages = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            messages.extend(conversation_history[-5:])
        messages.append({"role": "user", "content": query})

        client, provider = get_ai_client()
        model = get_model_name()

        logger.info(f"[RETRIEVER] Calling {provider}/{model} with {len(context)} context chars")

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=getattr(settings, "AI_TEMPERATURE", 0.3),
        )

        answer = response.choices[0].message.content

        return {
            "answer": answer,
            "model": model,
            "provider": provider,
            "tokens_used": response.usage.total_tokens if response.usage else 0,
            "finish_reason": response.choices[0].finish_reason,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Full pipeline
    # ──────────────────────────────────────────────────────────────────────────

    def query_and_respond(
        self,
        tenant_id: str,
        query: str,
        n_results: int = 5,
        conversation_history: Optional[List[Dict]] = None,
        filter_metadata: Optional[Dict] = None,
    ) -> Dict:
        """
        Full RAG pipeline: embed query → retrieve chunks → generate response.

        Generic queries (summarise, overview, etc.) fetch more chunks and skip
        the relevance threshold so the LLM gets a broad view of the corpus.
        Specific queries filter by self.relevance_threshold (default 0.1).

        FIX-7: relevance_scores are derived inline from the distances list so the
        three-way zip(docs, metas, scores) is always consistent.
        """
        generic_keywords = [
            "summarize", "summarise", "summary", "explain", "overview",
            "describe", "what is in", "list documents", "what documents",
        ]
        is_generic = any(kw in query.lower() for kw in generic_keywords)

        k = 20 if is_generic else max(n_results, 5)  # always retrieve at least 5

        retrieval = self.retrieve(
            tenant_id=tenant_id,
            query=query,
            n_results=k,
            filter_metadata=filter_metadata,
        )

        # FIX-7: build parallel lists from the same retrieval dict
        relevant_docs: List[str] = []
        relevant_sources: List[Dict] = []
        total_chars = 0

        for doc, meta, score in zip(
            retrieval["documents"],
            retrieval["metadatas"],
            retrieval["relevance_scores"],
        ):
            # For specific queries, skip below-threshold chunks
            if not is_generic and score < self.relevance_threshold:
                logger.debug(
                    f"[RETRIEVER] Skipping chunk (score={score:.3f} < threshold={self.relevance_threshold})"
                )
                continue

            # Respect context size cap
            if total_chars + len(doc) > self.max_context_chars:
                remaining = self.max_context_chars - total_chars
                if remaining > 100:
                    doc = doc[:remaining]
                else:
                    break

            relevant_docs.append(doc)
            total_chars += len(doc)
            relevant_sources.append({
                "document_id": meta.get("document_id"),
                "chunk_index": meta.get("chunk_index"),
                "relevance_score": round(score, 3),
                "title": meta.get("title", "Unknown"),
            })

        logger.info(
            f"[RETRIEVER] After filtering: {len(relevant_docs)} chunks kept "
            f"({total_chars} chars) for LLM context"
        )

        # ── No relevant chunks ──────────────────────────────────────────────
        if not relevant_docs:
            if retrieval["count"] == 0:
                # Nothing in ChromaDB at all for this tenant
                no_docs_msg = (
                    "No documents are available in the knowledge base."
                    if is_generic
                    else STRICT_FALLBACK_MESSAGE
                )
            else:
                # Chunks exist but all scored below threshold — edge case
                # Lower the bar and retry with everything we got
                logger.warning(
                    "[RETRIEVER] All chunks below threshold — using top results regardless of score."
                )
                relevant_docs = retrieval["documents"]
                relevant_sources = [
                    {
                        "document_id": m.get("document_id"),
                        "chunk_index": m.get("chunk_index"),
                        "relevance_score": round(s, 3),
                        "title": m.get("title", "Unknown"),
                    }
                    for m, s in zip(retrieval["metadatas"], retrieval["relevance_scores"])
                ]
                no_docs_msg = None  # will generate normally below

            if not relevant_docs:
                return {
                    "answer": no_docs_msg,
                    "sources": [],
                    "confidence": 0.0,
                    "tokens_used": 0,
                }

        # ── Generate response ───────────────────────────────────────────────
        try:
            generation = self.generate_response(
                query=query,
                context_documents=relevant_docs,
                conversation_history=conversation_history,
            )
        except Exception as e:
            logger.error(f"[RETRIEVER] LLM call failed: {e}", exc_info=True)
            raise

        avg_score = (
            sum(s["relevance_score"] for s in relevant_sources) / len(relevant_sources)
            if relevant_sources else 0.0
        )

        return {
            "answer": generation["answer"],
            "sources": relevant_sources,
            "confidence": round(avg_score, 3),
            "tokens_used": generation.get("tokens_used", 0),
            "num_sources": len(relevant_sources),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Prompt helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _build_context(self, documents: List[str]) -> str:
        """Concatenate chunks into a numbered context block."""
        if not documents:
            return ""
        parts = [f"[Document Chunk {i}]\n{doc}" for i, doc in enumerate(documents, 1)]
        return "\n\n".join(parts)

    def _build_system_prompt(self, context: str) -> str:
        return (
            "You are a document-based AI assistant. Answer questions strictly from the "
            "retrieved document context provided below. If the answer is in the context, "
            "give a clear, direct, factual answer using that information. Do not use "
            "general knowledge. Do not guess. Do not say 'the information is not available' "
            "if the context contains a relevant answer.\n\n"
            f"Retrieved context:\n{context}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Conversation manager
# ──────────────────────────────────────────────────────────────────────────────

class ConversationManager:
    """Manages in-process conversation history for context-aware responses."""

    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.conversations: Dict[str, List[Dict]] = {}

    def add_message(self, conversation_id: str, role: str, content: str):
        history = self.conversations.setdefault(conversation_id, [])
        history.append({"role": role, "content": content})
        if len(history) > self.max_history:
            self.conversations[conversation_id] = history[-self.max_history:]

    def get_history(self, conversation_id: str) -> List[Dict]:
        return self.conversations.get(conversation_id, [])

    def clear_history(self, conversation_id: str):
        self.conversations.pop(conversation_id, None)

    def get_all_conversations(self) -> List[str]:
        return list(self.conversations.keys())