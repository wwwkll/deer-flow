"use client";

import { HeartIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  useAddFavorite,
  useRemoveFavorite,
} from "@/core/agent-favorites/hooks";

interface FavoriteButtonProps {
  agentName: string;
  isFavorited: boolean;
}

export function FavoriteButton({
  agentName,
  isFavorited,
}: FavoriteButtonProps) {
  const addFavorite = useAddFavorite();
  const removeFavorite = useRemoveFavorite();

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isFavorited) {
      removeFavorite.mutate(agentName);
    } else {
      addFavorite.mutate(agentName);
    }
  };

  return (
    <Button
      size="icon"
      variant="ghost"
      className="h-8 w-8 shrink-0"
      onClick={handleClick}
      title={isFavorited ? "取消收藏" : "收藏"}
    >
      <HeartIcon
        className={`h-4 w-4 ${
          isFavorited ? "fill-red-500 text-red-500" : "text-muted-foreground"
        }`}
      />
    </Button>
  );
}
