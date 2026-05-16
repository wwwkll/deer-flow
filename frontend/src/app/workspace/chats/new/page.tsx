"use client";

import { useEffect } from "react";

export default function NewChatPage() {
  useEffect(() => {
    window.location.href = "/workspace/agents/novel-master/chats/new";
  }, []);

  return (
    <div className="flex size-full items-center justify-center">
      <p className="text-muted-foreground text-sm">正在跳转到 Novel Master...</p>
    </div>
  );
}
