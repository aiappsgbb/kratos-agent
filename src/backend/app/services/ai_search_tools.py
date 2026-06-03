"""Azure AI Search index management — create indexes and ingest PDFs.

Provides two main capabilities:
1. Create a new search index with a standard schema (content + metadata + vector).
2. Ingest a folder of PDF files into a target index, chunking pages and
   optionally generating embeddings via the Foundry OpenAI endpoint.

Uses DefaultAzureCredential for keyless auth — no API keys needed.
"""

import hashlib
import logging
import math
import os
from pathlib import Path

import fitz  # pymupdf
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────

# Folder where PDFs to ingest are located — override via env var
# Default resolves to <repo-root>/use-cases/insurance/sample-data
# CHANGE the folder name to ingest sample-data accordingly
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
PDF_INGEST_FOLDER = os.environ.get(
    "PDF_INGEST_FOLDER", str(_REPO_ROOT / "use-cases" / "wealth-management" / "sample-data")
)

# Embedding model deployment name on Foundry/OpenAI (set to empty to skip vectors)
EMBEDDING_DEPLOYMENT = os.environ.get("EMBEDDING_DEPLOYMENT", "text-embedding-ada-002")

# Chunk size in characters for splitting long pages
CHUNK_SIZE = int(os.environ.get("AI_SEARCH_CHUNK_SIZE", "2000"))
CHUNK_OVERLAP = int(os.environ.get("AI_SEARCH_CHUNK_OVERLAP", "200"))

# Vector dimensions — 1536 for text-embedding-ada-002 / text-embedding-3-small
VECTOR_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))

# Batch size for uploading documents to the index
UPLOAD_BATCH_SIZE = int(os.environ.get("AI_SEARCH_UPLOAD_BATCH_SIZE", "50"))


def _get_ai_search_endpoint() -> str:
    endpoint = os.environ.get("AZURE_AI_SEARCH_ENDPOINT", "")
    if not endpoint:
        raise ValueError("AZURE_AI_SEARCH_ENDPOINT environment variable is not set")
    return endpoint


def _get_credential() -> DefaultAzureCredential:
    return DefaultAzureCredential()


# ─── Index Creation ───────────────────────────────────────────────────────────


def _build_index_fields(include_vector: bool) -> list:
    """Build the standard field schema for a document search index."""
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        SearchableField(name="content", type=SearchFieldDataType.String, analyzer_name="en.microsoft"),
        SearchableField(name="title", type=SearchFieldDataType.String, filterable=True, sortable=True),
        SimpleField(name="source", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="page_number", type=SearchFieldDataType.Int32, filterable=True, sortable=True),
        SimpleField(name="chunk_index", type=SearchFieldDataType.Int32, filterable=True),
    ]
    if include_vector:
        fields.append(
            SearchField(
                name="content_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=VECTOR_DIMENSIONS,
                vector_search_profile_name="default-vector-profile",
            )
        )
    return fields


def _build_semantic_config() -> SemanticSearch:
    """Build a semantic search configuration targeting the content field."""
    return SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name="default",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[SemanticField(field_name="content")],
                ),
            )
        ]
    )


def _build_vector_search() -> VectorSearch:
    """Build a vector search configuration with HNSW algorithm."""
    return VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="default-hnsw")],
        profiles=[
            VectorSearchProfile(
                name="default-vector-profile",
                algorithm_configuration_name="default-hnsw",
            )
        ],
    )


def create_index(index_name: str, include_vector: bool | None = None) -> dict:
    """Create a new Azure AI Search index.

    Args:
        index_name: The name for the new index.
        include_vector: Whether to include a vector field. Defaults to True if
                        EMBEDDING_DEPLOYMENT is configured, False otherwise.

    Returns:
        Dict with status and index details.
    """
    if not index_name or not index_name.strip():
        return {"status": "error", "message": "index_name is required"}

    index_name = index_name.strip()

    if include_vector is None:
        include_vector = bool(EMBEDDING_DEPLOYMENT)

    endpoint = _get_ai_search_endpoint()
    credential = _get_credential()
    index_client = SearchIndexClient(endpoint=endpoint, credential=credential)

    fields = _build_index_fields(include_vector)
    semantic_search = _build_semantic_config()

    index = SearchIndex(
        name=index_name,
        fields=fields,
        semantic_search=semantic_search,
    )

    if include_vector:
        index.vector_search = _build_vector_search()

    result = index_client.create_or_update_index(index)
    logger.info("Created/updated index '%s' with %d fields (vector=%s)", index_name, len(fields), include_vector)

    return {
        "status": "success",
        "index_name": result.name,
        "fields": [f.name for f in result.fields],
        "include_vector": include_vector,
    }


# ─── PDF Ingestion ────────────────────────────────────────────────────────────


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks."""
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def _extract_pages_from_pdf(pdf_path: Path) -> list[dict]:
    """Extract text from a PDF file, returning one entry per page."""
    pages = []
    with fitz.open(str(pdf_path)) as doc:
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text("text")
            if text and text.strip():
                pages.append({"page_number": page_num, "text": text.strip()})
    return pages


def _generate_embeddings(texts: list[str], credential: DefaultAzureCredential) -> list[list[float]] | None:
    """Generate embeddings via the Foundry OpenAI endpoint.

    Returns None if EMBEDDING_DEPLOYMENT is not configured.
    """
    if not EMBEDDING_DEPLOYMENT:
        return None

    foundry_endpoint = os.environ.get("FOUNDRY_ENDPOINT", "")
    if not foundry_endpoint:
        logger.warning("FOUNDRY_ENDPOINT not set — skipping embedding generation")
        return None

    import httpx

    account_name = foundry_endpoint.rstrip("/").split("//")[1].split(".")[0]
    embeddings_url = (
        f"https://{account_name}.services.ai.azure.com/openai/deployments/"
        f"{EMBEDDING_DEPLOYMENT}/embeddings?api-version=2024-10-21"
    )

    token = credential.get_token("https://cognitiveservices.azure.com/.default")

    all_embeddings = []
    # Process in batches of 16 to stay within API limits
    batch_size = 16
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = httpx.post(
            embeddings_url,
            headers={
                "Authorization": f"Bearer {token.token}",
                "Content-Type": "application/json",
            },
            json={"input": batch, "model": EMBEDDING_DEPLOYMENT},
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        for item in sorted(data["data"], key=lambda x: x["index"]):
            all_embeddings.append(item["embedding"])

    return all_embeddings


def ingest_pdfs(index_name: str, pdf_folder: str | None = None) -> dict:
    """Ingest all PDF files from a folder into an Azure AI Search index.

    Each PDF page is extracted, chunked, and uploaded as individual documents.
    If an embedding deployment is configured, vector embeddings are generated.

    Args:
        index_name: The target search index (must already exist).
        pdf_folder: Folder containing PDF files. Defaults to PDF_INGEST_FOLDER env var.

    Returns:
        Dict with ingestion status and document counts.
    """
    if not index_name or not index_name.strip():
        return {"status": "error", "message": "index_name is required"}

    folder = Path(pdf_folder) if pdf_folder else Path(PDF_INGEST_FOLDER)
    if not folder.exists():
        return {"status": "error", "message": f"PDF folder does not exist: {folder}"}

    pdf_files = sorted(folder.glob("*.pdf"))
    if not pdf_files:
        return {"status": "error", "message": f"No PDF files found in {folder}"}

    endpoint = _get_ai_search_endpoint()
    credential = _get_credential()
    search_client = SearchClient(endpoint=endpoint, index_name=index_name, credential=credential)

    # Extract and chunk all PDFs
    documents = []
    for pdf_path in pdf_files:
        logger.info("Processing PDF: %s", pdf_path.name)
        try:
            pages = _extract_pages_from_pdf(pdf_path)
        except Exception as e:
            logger.error("Failed to extract %s: %s", pdf_path.name, e)
            continue

        for page in pages:
            chunks = _chunk_text(page["text"])
            for chunk_idx, chunk in enumerate(chunks):
                # Deterministic ID: same file+page+chunk always produces the same ID
                # so re-runs update existing docs instead of creating duplicates
                id_seed = f"{pdf_path.name}:{page['page_number']}:{chunk_idx}"
                doc_id = hashlib.sha256(id_seed.encode()).hexdigest()[:32]
                documents.append(
                    {
                        "id": doc_id,
                        "content": chunk,
                        "title": pdf_path.stem,
                        "source": pdf_path.name,
                        "page_number": page["page_number"],
                        "chunk_index": chunk_idx,
                    }
                )

    if not documents:
        return {"status": "error", "message": "No text content extracted from PDFs"}

    # Generate embeddings if configured
    include_vector = bool(EMBEDDING_DEPLOYMENT)
    if include_vector:
        logger.info("Generating embeddings for %d chunks...", len(documents))
        try:
            texts = [doc["content"] for doc in documents]
            embeddings = _generate_embeddings(texts, credential)
            if embeddings and len(embeddings) == len(documents):
                for doc, emb in zip(documents, embeddings, strict=False):
                    doc["content_vector"] = emb
            else:
                logger.warning("Embedding count mismatch — uploading without vectors")
                include_vector = False
        except Exception as e:
            logger.error("Embedding generation failed: %s — uploading without vectors", e)
            include_vector = False

    # Upload in batches
    total_uploaded = 0
    total_failed = 0
    num_batches = math.ceil(len(documents) / UPLOAD_BATCH_SIZE)

    for batch_idx in range(num_batches):
        start = batch_idx * UPLOAD_BATCH_SIZE
        batch = documents[start : start + UPLOAD_BATCH_SIZE]
        try:
            result = search_client.merge_or_upload_documents(documents=batch)
            succeeded = sum(1 for r in result if r.succeeded)
            failed = len(batch) - succeeded
            total_uploaded += succeeded
            total_failed += failed
            logger.info("Batch %d/%d: %d uploaded, %d failed", batch_idx + 1, num_batches, succeeded, failed)
        except Exception as e:
            logger.error("Batch %d/%d upload failed: %s", batch_idx + 1, num_batches, e)
            total_failed += len(batch)

    logger.info(
        "Ingestion complete — index=%s pdfs=%d chunks=%d uploaded=%d failed=%d vectors=%s",
        index_name,
        len(pdf_files),
        len(documents),
        total_uploaded,
        total_failed,
        include_vector,
    )

    return {
        "status": "success",
        "index_name": index_name,
        "pdf_files_processed": len(pdf_files),
        "total_chunks": len(documents),
        "uploaded": total_uploaded,
        "failed": total_failed,
        "include_vector": include_vector,
    }


def delete_index(index_name: str) -> dict:
    """Delete an Azure AI Search index.

    Args:
        index_name: The index to delete.

    Returns:
        Dict with status.
    """
    if not index_name or not index_name.strip():
        return {"status": "error", "message": "index_name is required"}

    endpoint = _get_ai_search_endpoint()
    credential = _get_credential()
    index_client = SearchIndexClient(endpoint=endpoint, credential=credential)
    index_client.delete_index(index_name.strip())
    logger.info("Deleted index '%s'", index_name)
    return {"status": "success", "index_name": index_name.strip(), "action": "deleted"}


# ─── CLI ──────────────────────────────────────────────────────────────────────


def _load_azd_env() -> None:
    """Load environment variables from the active azd environment."""
    import subprocess

    try:
        proc = subprocess.run(
            ["azd", "env", "get-values"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            logger.warning("azd env get-values failed (rc=%s) — skipping", proc.returncode)
            return
    except FileNotFoundError:
        logger.debug("azd CLI not found — skipping env loading")
        return

    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip('"').strip("'")
        os.environ.setdefault(key, value)


if __name__ == "__main__":
    import argparse

    _load_azd_env()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")

    parser = argparse.ArgumentParser(description="Azure AI Search index management")
    sub = parser.add_subparsers(dest="command", required=True)

    create_p = sub.add_parser("create-index", help="Create a new search index")
    create_p.add_argument("index_name", help="Name for the new index")
    create_p.add_argument("--no-vector", action="store_true", help="Skip vector field")

    ingest_p = sub.add_parser("ingest", help="Ingest PDFs into an index")
    ingest_p.add_argument("index_name", help="Target index name")
    ingest_p.add_argument("--folder", default=None, help="PDF folder (default: PDF_INGEST_FOLDER env)")

    delete_p = sub.add_parser("delete-index", help="Delete a search index")
    delete_p.add_argument("index_name", help="Name of the index to delete")

    args = parser.parse_args()
    import json

    if args.command == "create-index":
        result = create_index(args.index_name, include_vector=not args.no_vector)
    elif args.command == "ingest":
        result = ingest_pdfs(args.index_name, pdf_folder=args.folder)
    elif args.command == "delete-index":
        result = delete_index(args.index_name)

    print(json.dumps(result, indent=2))
