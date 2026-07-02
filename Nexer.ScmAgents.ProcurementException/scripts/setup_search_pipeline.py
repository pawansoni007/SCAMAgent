"""
setup_search_pipeline.py

One-time / re-runnable provisioning script for the procurement policy
RAG pipeline on Azure AI Search.

Replaces the old manual flow:
    policies/*.json -> ingest_policies.py -> manual embed + upsert

With the production flow:
    Blob Storage (real policy docs)
        -> Azure AI Search Indexer
            -> Skillset (Split Skill + AzureOpenAIEmbedding Skill)
                -> Index (procurement-policies)
        -> runs on a schedule, auto-syncs when blobs change

This script is idempotent: running it again updates the data source,
index, skillset, and indexer definitions in place (create_or_update),
it does not duplicate them.

SCHEMA NOTE (patched): added policy_id and tenant_id as real, filterable
index fields, and matching index-projection mappings reading from blob
metadata (/document/policy_id, /document/tenant_id). policy_service.py
requires both of these -- it filters on tenant_id and selects policy_id
for citations. upload_policy_docs.py already attaches both as blob
metadata via _manifest.json, so no upload-side changes are needed.

Required environment variables (put these in local.settings.json for
local runs, and as Function App settings / Key Vault references for
deployed runs -- never hardcode any of these):

    AZURE_SEARCH_ENDPOINT              e.g. https://scm-agent-search.search.windows.net
    AZURE_STORAGE_ACCOUNT_RESOURCE_ID  full ARM resource ID of the storage account, e.g.
                                        /subscriptions/<sub-id>/resourceGroups/<rg>/providers/
                                        Microsoft.Storage/storageAccounts/<account-name>
    AZURE_OPENAI_ENDPOINT              e.g. https://scm-agents-pack-dev-openai-ac92.openai.azure.com
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT  deployment name, e.g. text-embedding-3-small

Auth (fully keyless -- no secrets stored anywhere):
    Uses DefaultAzureCredential for the provisioning calls this script
    makes (creating the index/skillset/indexer/data source).

    For the data source's own connection to Blob Storage, this script
    uses Azure AI Search's "ResourceId=" connection-string format
    (see https://learn.microsoft.com/azure/search/search-howto-managed-identities-data-sources).
    This contains no account key at all -- it just tells Search "use
    your own managed identity to reach this storage account." That is
    why AZURE_STORAGE_ACCOUNT_RESOURCE_ID is a resource ID, not a
    connection string with a key in it. Note: depending on your
    installed azure-search-documents version, this connection string
    is passed as a flat `connection_string` field directly on
    SearchIndexerDataSourceConnection, or nested inside a
    DataSourceCredentials object on newer SDK majors -- check your
    installed version with `pip show azure-search-documents` if you
    hit a TypeError here after an SDK upgrade.

    At indexing/query time, the SEARCH SERVICE's system-assigned
    managed identity is what actually calls Blob Storage and Azure
    OpenAI -- not this script's identity. That identity needs:
        - Storage Blob Data Reader          on the storage account
        - Cognitive Services OpenAI User    on the Azure OpenAI resource
    Girish needs to grant those two roles to the SEARCH SERVICE's
    identity (not to your Function App's identity -- that was for the
    old approach). See create_data_source() below for how to fetch the
    Search service's principal ID to give him.
"""

import os
import sys
from datetime import timedelta

from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient, SearchIndexerClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SearchField,
    SearchFieldDataType,
    SimpleField,
    SearchableField,
    VectorSearch,
    VectorSearchProfile,
    HnswAlgorithmConfiguration,
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
    SearchIndexerDataSourceConnection,
    SearchIndexerDataSourceType,
    SearchIndexerDataContainer,
    SearchIndexerSkillset,
    SplitSkill,
    AzureOpenAIEmbeddingSkill,
    InputFieldMappingEntry,
    OutputFieldMappingEntry,
    SearchIndexer,
    FieldMapping,
    IndexingSchedule,
    SearchIndexerIndexProjection,
    SearchIndexerIndexProjectionSelector,
    SearchIndexerIndexProjectionsParameters,
    IndexProjectionMode,
)

# ---------------------------------------------------------------------------
# Configuration -- all from environment, nothing hardcoded
# ---------------------------------------------------------------------------

SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
STORAGE_ACCOUNT_RESOURCE_ID = os.environ["AZURE_STORAGE_ACCOUNT_RESOURCE_ID"]
BLOB_CONTAINER_NAME = os.environ.get("POLICY_BLOB_CONTAINER", "procurement-policies-docs")

OPENAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
EMBEDDING_DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
EMBEDDING_DIMENSIONS = int(os.environ.get("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "1536"))

INDEX_NAME = os.environ.get("POLICY_INDEX_NAME", "procurement-policies")
DATA_SOURCE_NAME = f"{INDEX_NAME}-blob-datasource"
SKILLSET_NAME = f"{INDEX_NAME}-skillset"
INDEXER_NAME = f"{INDEX_NAME}-indexer"

credential = DefaultAzureCredential()


def create_data_source(indexer_client: SearchIndexerClient) -> None:
    """
    Points Azure AI Search at the blob container holding policy docs,
    using a keyless "ResourceId=" connection string so the Search
    service's managed identity is used at indexing time -- no storage
    account key is ever stored anywhere.
    """
    print(f"Creating/updating data source '{DATA_SOURCE_NAME}' -> container '{BLOB_CONTAINER_NAME}'")

    keyless_connection_string = f"ResourceId={STORAGE_ACCOUNT_RESOURCE_ID};"

    data_source = SearchIndexerDataSourceConnection(
        name=DATA_SOURCE_NAME,
        type=SearchIndexerDataSourceType.AZURE_BLOB,
        connection_string=keyless_connection_string,
        container=SearchIndexerDataContainer(name=BLOB_CONTAINER_NAME),
    )
    indexer_client.create_or_update_data_source_connection(data_source)


def create_index(index_client: SearchIndexClient) -> None:
    """
    Chunk-level index. One document in this index = one chunk of one
    policy file, not one whole policy. This is the standard RAG-over-
    documents pattern (matches what the Split Skill + index projections
    below produce).

    PATCHED: added policy_id and tenant_id as real, filterable fields.
    policy_service.py requires both -- tenant_id is used in an OData
    filter (tenant_id eq '...') and policy_id is selected for citations
    (e.g. POL-001) in agent recommendations. Both must be filterable
    (tenant_id genuinely needs filter support; policy_id is marked
    filterable too in case future lookups need it, at negligible cost).
    """
    print(f"Creating/updating index '{INDEX_NAME}'")

    fields = [
        # NOTE: must use SearchField (not SimpleField) for the key field here.
        # SimpleField silently drops analyzer_name and forces searchable=False,
        # but Azure AI Search requires the key field of an index used as an
        # index-projection target to have searchable=True AND the keyword
        # analyzer explicitly set (verified: SimpleField does not support this).
        SearchField(name="chunk_id", type=SearchFieldDataType.String, key=True,
                    searchable=True, analyzer_name="keyword"),
        SimpleField(name="parent_id", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SearchableField(name="chunk", type=SearchFieldDataType.String),
        SimpleField(name="category", type=SearchFieldDataType.String,
                    filterable=True, facetable=True),
        # --- PATCH: new fields required by policy_service.py ---
        SimpleField(name="policy_id", type=SearchFieldDataType.String,
                    filterable=True),
        SimpleField(name="tenant_id", type=SearchFieldDataType.String,
                    filterable=True),
        # --- end patch ---
        SearchField(
            name="vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name="vector-profile",
        ),
    ]

    vector_search = VectorSearch(
        profiles=[
            VectorSearchProfile(
                name="vector-profile",
                algorithm_configuration_name="hnsw-algo",
                vectorizer_name="openai-vectorizer",
            )
        ],
        algorithms=[HnswAlgorithmConfiguration(name="hnsw-algo")],
        vectorizers=[
            AzureOpenAIVectorizer(
                vectorizer_name="openai-vectorizer",
                parameters=AzureOpenAIVectorizerParameters(
                    resource_url=OPENAI_ENDPOINT,
                    deployment_name=EMBEDDING_DEPLOYMENT,
                    model_name=EMBEDDING_DEPLOYMENT,
                ),
            )
        ],
    )

    index = SearchIndex(name=INDEX_NAME, fields=fields, vector_search=vector_search)
    index_client.create_or_update_index(index)


def create_skillset(indexer_client: SearchIndexerClient) -> None:
    """
    Split Skill -> chunks each document.
    AzureOpenAIEmbedding Skill -> embeds each chunk via your real deployment.
    Index Projections -> writes one search document per chunk into the index.
    No custom code generates embeddings; Search calls Azure OpenAI directly
    using the managed identity of the Search service.

    PATCHED: index projection mappings now also carry policy_id and
    tenant_id from blob metadata (/document/policy_id, /document/tenant_id).
    upload_policy_docs.py already sets these as blob metadata (read from
    policies_docs/_manifest.json, written by convert_policies_to_docs.py),
    so no upload-side changes are needed -- this just wires the existing
    metadata through to the new index fields.
    """
    print(f"Creating/updating skillset '{SKILLSET_NAME}'")

    split_skill = SplitSkill(
        description="Split policy documents into chunks for embedding",
        text_split_mode="pages",
        context="/document",
        maximum_page_length=2000,
        page_overlap_length=200,
        inputs=[InputFieldMappingEntry(name="text", source="/document/content")],
        outputs=[OutputFieldMappingEntry(name="textItems", target_name="pages")],
    )

    embedding_skill = AzureOpenAIEmbeddingSkill(
        description="Generate embeddings for each policy chunk",
        context="/document/pages/*",
        resource_url=OPENAI_ENDPOINT,
        deployment_name=EMBEDDING_DEPLOYMENT,
        model_name=EMBEDDING_DEPLOYMENT,
        dimensions=EMBEDDING_DIMENSIONS,
        inputs=[InputFieldMappingEntry(name="text", source="/document/pages/*")],
        outputs=[OutputFieldMappingEntry(name="embedding", target_name="vector")],
    )

    index_projections = SearchIndexerIndexProjection(
        selectors=[
            SearchIndexerIndexProjectionSelector(
                target_index_name=INDEX_NAME,
                parent_key_field_name="parent_id",
                source_context="/document/pages/*",
                mappings=[
                    InputFieldMappingEntry(name="chunk", source="/document/pages/*"),
                    InputFieldMappingEntry(name="vector", source="/document/pages/*/vector"),

                    InputFieldMappingEntry(name="title", source="/document/title"),

                    InputFieldMappingEntry(name="category", source="/document/category"),

                    # --- PATCH: new mappings required by policy_service.py ---
                    InputFieldMappingEntry(name="policy_id", source="/document/policy_id"),

                    InputFieldMappingEntry(name="tenant_id", source="/document/tenant_id"),
                    # --- end patch ---
                ],
            )
        ],
        parameters=SearchIndexerIndexProjectionsParameters(
            projection_mode=IndexProjectionMode.SKIP_INDEXING_PARENT_DOCUMENTS
        ),
    )

    skillset = SearchIndexerSkillset(
        name=SKILLSET_NAME,
        description="Chunk + embed procurement policy documents",
        skills=[split_skill, embedding_skill],
        index_projection=index_projections,
    )
    indexer_client.create_or_update_skillset(skillset)


def create_indexer(indexer_client: SearchIndexerClient) -> None:
    """
    Ties data source + skillset + index together and runs on a schedule,
    so the index stays in sync automatically when files are added,
    updated, or removed from the blob container. This replaces the
    manual "rerun the script by hand" step entirely.
    """
    print(f"Creating/updating indexer '{INDEXER_NAME}'")

    indexer = SearchIndexer(
        name=INDEXER_NAME,
        data_source_name=DATA_SOURCE_NAME,
        target_index_name=INDEX_NAME,
        skillset_name=SKILLSET_NAME,
        field_mappings=[
            FieldMapping(source_field_name="metadata_storage_path", target_field_name="parent_id"),
        ],
        schedule=IndexingSchedule(interval=timedelta(minutes=15)),  # re-check blob container every 15 minutes
    )
    indexer_client.create_or_update_indexer(indexer)


def main() -> None:
    index_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=credential)
    indexer_client = SearchIndexerClient(endpoint=SEARCH_ENDPOINT, credential=credential)

    print(
        "Before running this, make sure the Search service has a "
        "system-assigned managed identity enabled, and send Girish its "
        "principal ID. Get it with:\n"
        "  az search service show --name <search-service-name> "
        "--resource-group <rg-name> --query identity.principalId -o tsv\n"
        "He needs to grant that principal:\n"
        "  - Storage Blob Data Reader on the storage account\n"
        "  - Cognitive Services OpenAI User on the Azure OpenAI resource\n"
    )

    create_data_source(indexer_client)
    create_index(index_client)
    create_skillset(indexer_client)
    create_indexer(indexer_client)

    print("\nRunning indexer now (instead of waiting for the schedule)...")
    indexer_client.run_indexer(INDEXER_NAME)

    print(
        "\nDone. Check status with:\n"
        f"  az search indexer-status show --name {INDEXER_NAME} "
        "--service-name <search-service-name> --resource-group <rg-name>\n"
        "or in the Azure Portal under your Search service -> Indexers."
    )


if __name__ == "__main__":
    main()