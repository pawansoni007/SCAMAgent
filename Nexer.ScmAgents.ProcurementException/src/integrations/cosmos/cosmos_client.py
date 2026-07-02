"""
Cosmos DB client factory.

Provides a singleton Cosmos container client for chat persistence.
All Cosmos access should go through this module.
"""

import os
from functools import lru_cache

from azure.cosmos import CosmosClient, ContainerProxy


@lru_cache(maxsize=1)
def get_chat_container() -> ContainerProxy:
    """
    Returns the configured chat conversation container.

    Uses a singleton CosmosClient instance via lru_cache
    to avoid recreating connections on every request.
    """

    endpoint = os.environ["COSMOS_ENDPOINT"]
    key = os.environ["COSMOS_KEY"]

    database_name = os.environ["COSMOS_DATABASE_NAME"]
    container_name = os.environ["COSMOS_CHAT_CONTAINER"]

    client = CosmosClient(endpoint, credential=key)

    database = client.get_database_client(database_name)

    return database.get_container_client(container_name)