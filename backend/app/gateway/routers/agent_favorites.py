"""Agent favorites API router."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deerflow.global_variables.storage import get_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-favorites", tags=["agent-favorites"])


class FavoritesResponse(BaseModel):
    """Response model for listing agent favorites."""

    favorites: list[str]


class FavoriteActionResponse(BaseModel):
    """Response model for favorite actions."""

    success: bool
    agent_name: str


@router.get(
    "",
    response_model=FavoritesResponse,
    summary="List Agent Favorites",
    description="Get all favorited agent names.",
)
async def list_favorites() -> FavoritesResponse:
    """Get all favorited agent names.

    Returns:
        List of favorited agent names ordered by creation time (newest first).
    """
    try:
        storage = get_storage()
        favorites = storage.list_agent_favorites()
        return FavoritesResponse(favorites=favorites)
    except Exception as e:
        logger.error(f"Failed to list agent favorites: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list favorites: {str(e)}")


@router.put(
    "/{agent_name}",
    response_model=FavoriteActionResponse,
    summary="Add Agent Favorite",
    description="Add an agent to favorites.",
)
async def add_favorite(agent_name: str) -> FavoriteActionResponse:
    """Add an agent to favorites.

    Args:
        agent_name: Name of the agent to favorite.

    Returns:
        Success status and agent name.
    """
    try:
        storage = get_storage()
        success = storage.add_agent_favorite(agent_name)
        return FavoriteActionResponse(success=success, agent_name=agent_name)
    except Exception as e:
        logger.error(f"Failed to add agent favorite: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to add favorite: {str(e)}")


@router.delete(
    "/{agent_name}",
    response_model=FavoriteActionResponse,
    summary="Remove Agent Favorite",
    description="Remove an agent from favorites.",
)
async def remove_favorite(agent_name: str) -> FavoriteActionResponse:
    """Remove an agent from favorites.

    Args:
        agent_name: Name of the agent to unfavorite.

    Returns:
        Success status and agent name.
    """
    try:
        storage = get_storage()
        success = storage.remove_agent_favorite(agent_name)
        return FavoriteActionResponse(success=success, agent_name=agent_name)
    except Exception as e:
        logger.error(f"Failed to remove agent favorite: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to remove favorite: {str(e)}")
