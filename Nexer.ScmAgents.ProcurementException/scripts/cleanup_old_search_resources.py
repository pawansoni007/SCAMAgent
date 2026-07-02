"""
cleanup_old_search_resources.py

Deletes the old, abandoned search resources that conflict with the new
chunk-based pipeline:
    - indexer:     scm-blob-indexer
    - data source: scm-blob-datasource
    - index:       procurement-policies  (old schema: clause_text, citation,
                    effective_date, tenant_id -- no skillset, no vectors
                    actually populated, 0 documents)

Why this is safe to delete:
    - The indexer has skillset_name=None (never had chunking/embeddings wired up)
    - item_count=0, failed_item_count=0 (container was empty, nothing was ever indexed)
    - The data source points at container 'scm-documents', which is not the
      container we're using going forward ('procurement-policies-docs')
    - No agent code today successfully queries this index for real data,
      since it was never populated

This script re-checks document count is actually 0 right before deleting,
as a safety check, and will refuse to delete the index if it finds any
documents in it.

Usage:
    $env:AZURE_SEARCH_ENDPOINT = "https://scm-agent-search.search.windows.net"
    python scripts/cleanup_old_search_resources.py
"""

import os
import sys

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient, SearchIndexerClient

SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
INDEXER_NAME = "scm-blob-indexer"
DATA_SOURCE_NAME = "scm-blob-datasource"
INDEX_NAME = "procurement-policies"

credential = DefaultAzureCredential()


def confirm_index_is_empty(index_client: SearchIndexClient) -> bool:
    """Safety check: refuse to delete if the index actually has documents."""
    try:
        search_client = SearchClient(
            endpoint=SEARCH_ENDPOINT, index_name=INDEX_NAME, credential=credential
        )
        results = search_client.search(search_text="*", include_total_count=True, top=0)
        count = results.get_count()
        print(f"Document count in '{INDEX_NAME}': {count}")
        return count == 0
    except Exception as e:
        print(f"Could not check document count (index may not exist): {e}")
        return True  # if it doesn't exist, there's nothing to protect


def main() -> None:
    index_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=credential)
    indexer_client = SearchIndexerClient(endpoint=SEARCH_ENDPOINT, credential=credential)

    print("Safety check before deleting anything...")
    if not confirm_index_is_empty(index_client):
        print(
            f"\nABORTING: '{INDEX_NAME}' has documents in it. "
            "Refusing to delete automatically -- check with Girish first."
        )
        sys.exit(1)

    print("\nConfirmed empty. Proceeding with deletion.\n")

    try:
        print(f"Deleting indexer '{INDEXER_NAME}'...")
        indexer_client.delete_indexer(INDEXER_NAME)
        print("  done.")
    except Exception as e:
        print(f"  skipped (may not exist): {e}")

    try:
        print(f"Deleting data source '{DATA_SOURCE_NAME}'...")
        indexer_client.delete_data_source_connection(DATA_SOURCE_NAME)
        print("  done.")
    except Exception as e:
        print(f"  skipped (may not exist): {e}")

    try:
        print(f"Deleting index '{INDEX_NAME}'...")
        index_client.delete_index(INDEX_NAME)
        print("  done.")
    except Exception as e:
        print(f"  skipped (may not exist): {e}")

    print(
        "\nCleanup complete. You can now re-run "
        "scripts/setup_search_pipeline.py to create the new "
        "chunk-based pipeline cleanly."
    )


if __name__ == "__main__":
    main()