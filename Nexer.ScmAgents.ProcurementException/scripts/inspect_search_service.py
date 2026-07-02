"""
inspect_search_service.py

READ-ONLY inspection script. Does not create, modify, or delete anything.
Lists all data sources, indexes, skillsets, and indexers currently on the
Search service, and shows exactly what 'scm-blob-indexer' (or any other
indexer) is wired to -- which data source, which skillset, which target
index.

Usage:
    $env:AZURE_SEARCH_ENDPOINT = "https://scm-agent-search.search.windows.net"
    python scripts/inspect_search_service.py
"""

import os
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient, SearchIndexerClient

SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
credential = DefaultAzureCredential()

index_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=credential)
indexer_client = SearchIndexerClient(endpoint=SEARCH_ENDPOINT, credential=credential)

print("=" * 70)
print("DATA SOURCES")
print("=" * 70)
for ds in indexer_client.get_data_source_connections():
    print(f"  name: {ds.name}")
    print(f"  type: {ds.type}")
    print(f"  container: {ds.container.name if ds.container else None}")
    cs = ds.connection_string or ""
    masked = cs[:40] + "..." if len(cs) > 40 else cs
    print(f"  connection_string (masked): {masked}")
    print()

print("=" * 70)
print("INDEXES")
print("=" * 70)
for idx in index_client.list_indexes():
    print(f"  name: {idx.name}")
    print(f"  fields: {[f.name for f in idx.fields]}")
    print()

print("=" * 70)
print("SKILLSETS")
print("=" * 70)
for sk in indexer_client.get_skillsets():
    print(f"  name: {sk.name}")
    print(f"  skills: {[type(s).__name__ for s in sk.skills]}")
    print()

print("=" * 70)
print("INDEXERS")
print("=" * 70)
for ixr in indexer_client.get_indexers():
    print(f"  name: {ixr.name}")
    print(f"  data_source_name: {ixr.data_source_name}")
    print(f"  skillset_name: {ixr.skillset_name}")
    print(f"  target_index_name: {ixr.target_index_name}")
    try:
        status = indexer_client.get_indexer_status(ixr.name)
        last = status.last_result
        print(f"  last_result status: {last.status if last else 'never run'}")
        if last and last.errors:
            print(f"  errors: {[e.error_message for e in last.errors]}")
        if last:
            print(f"  item_count: {last.item_count}, failed_item_count: {last.failed_item_count}")
    except Exception as e:
        print(f"  could not get status: {e}")
    print()