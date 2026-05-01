import {
  BookIcon,
  ChevronRightIcon,
  FolderIcon,
  FolderOpenIcon,
  Loader2Icon,
  Maximize2Icon,
  Minimize2Icon,
  RefreshCwIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { getFileIcon, getFileName } from "@/core/utils/files";
import { cn } from "@/lib/utils";

import { useArtifacts } from "./context";

function SimpleFileList({
  className,
  files,
  onSelect,
}: {
  className?: string;
  files: string[];
  onSelect: (file: string) => void;
}) {
  const items = useMemo(
    () =>
      files.map((f) => ({
        path: f,
        name: getFileName(f),
      })),
    [files],
  );

  return (
    <div className={cn("size-full overflow-auto p-2", className)}>
      {items.map((item) => (
        <div
          key={item.path}
          className="hover:bg-accent flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5"
          onClick={() => onSelect(item.path)}
        >
          {getFileIcon(item.name, "h-4 w-4 shrink-0")}
          <span className="truncate text-sm">{item.name}</span>
        </div>
      ))}
    </div>
  );
}

export function ArtifactFileList({
  className,
  files,
  threadId: _threadId,
}: {
  className?: string;
  files?: string[];
  threadId: string;
}) {
  const {
    directoryEntries,
    expandedFolders,
    isLoadingDirectory,
    novelToc,
    isLoadingNovelToc,
    select,
    toggleFolder,
    loadDirectory,
    loadFolderChildren,
    expandAll,
    collapseAll,
    refreshDirectory,
  } = useArtifacts();

  const [error, setError] = useState<string | null>(null);
  const [initialized, setInitialized] = useState(false);

  const hasProvidedFiles = files && files.length > 0;
  const hasNovelToc = novelToc !== null || isLoadingNovelToc;

  const novelName = novelToc
    ? (novelToc.split("/").filter(Boolean).pop() ?? novelToc)
    : null;

  useEffect(() => {
    if (!hasNovelToc) return;
    if (isLoadingNovelToc) return;
    if (initialized) return;

    setError(null);
    setInitialized(true);

    void loadDirectory(novelToc!).catch((err) => {
      console.error("Failed to load directory:", err);
      setError(
        "Failed to connect to backend API. Make sure the backend server is running.",
      );
    });
  }, [hasNovelToc, isLoadingNovelToc, novelToc, initialized, loadDirectory]);

  const rootEntries = novelToc ? (directoryEntries[novelToc] ?? []) : [];

  const handleSelect = useCallback(
    (file: string) => {
      select(`workspace:${file}`);
    },
    [select],
  );

  const handleProvidedFileSelect = useCallback(
    (file: string) => {
      select(file);
    },
    [select],
  );

  const handleToggleFolder = useCallback(
    (path: string) => {
      toggleFolder(path);
      if (!expandedFolders.has(path) && !directoryEntries[path]) {
        void loadFolderChildren(path);
      }
    },
    [toggleFolder, expandedFolders, directoryEntries, loadFolderChildren],
  );

  const renderEntry = (
    entry: { name: string; path: string; isDirectory: boolean },
    depth = 0,
  ) => {
    const isExpanded = expandedFolders.has(entry.path);
    const paddingLeft = depth * 16 + 8;

    if (entry.isDirectory) {
      return (
        <div key={entry.path}>
          <div
            className={cn(
              "hover:bg-accent flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5",
            )}
            style={{ paddingLeft }}
            onClick={() => handleToggleFolder(entry.path)}
          >
            {isExpanded ? (
              <FolderOpenIcon className="text-muted-foreground h-4 w-4 shrink-0" />
            ) : (
              <FolderIcon className="text-muted-foreground h-4 w-4 shrink-0" />
            )}
            <span className="truncate text-sm font-medium">{entry.name}</span>
            <ChevronRightIcon
              className={cn(
                "text-muted-foreground ml-auto h-4 w-4 shrink-0 transition-transform",
                isExpanded && "rotate-90",
              )}
            />
          </div>
          {isExpanded && directoryEntries[entry.path] && (
            <div>
              {(directoryEntries[entry.path] ?? []).map((child) =>
                renderEntry(child, depth + 1),
              )}
            </div>
          )}
        </div>
      );
    }

    return (
      <div
        key={entry.path}
        className={cn(
          "hover:bg-accent flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5",
        )}
        style={{ paddingLeft }}
        onClick={() => handleSelect(entry.path)}
      >
        {getFileIcon(entry.name, "h-4 w-4 shrink-0")}
        <span className="truncate text-sm">{entry.name}</span>
      </div>
    );
  };

  if (!hasNovelToc) {
    if (hasProvidedFiles) {
      return (
        <SimpleFileList
          className={className}
          files={files}
          onSelect={handleProvidedFileSelect}
        />
      );
    }

    return (
      <div
        className={cn(
          "flex size-full flex-col items-center justify-center gap-3 px-4",
          className,
        )}
      >
        <BookIcon className="text-muted-foreground h-8 w-8" />
        <p className="text-muted-foreground text-center text-sm">
          此对话未设置小说标签
          <br />
          请先新建对话并选择小说标签
        </p>
      </div>
    );
  }

  if (isLoadingNovelToc) {
    return (
      <div
        className={cn("flex size-full items-center justify-center", className)}
      >
        <Loader2Icon className="text-muted-foreground h-5 w-5 animate-spin" />
      </div>
    );
  }

  return (
    <div className={cn("size-full overflow-auto", className)}>
      <div className="bg-background sticky top-0 z-10 flex items-center gap-2 border-b px-2 py-2">
        {novelName && (
          <span className="text-foreground flex min-w-0 flex-1 items-center gap-1.5 truncate text-xs font-medium">
            <BookIcon className="h-3.5 w-3.5 shrink-0" />
            {novelName}
          </span>
        )}
        <div className="flex shrink-0 items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={expandAll}
            title="Expand all"
          >
            <Maximize2Icon className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={collapseAll}
            title="Collapse all"
          >
            <Minimize2Icon className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => void refreshDirectory()}
            title="Refresh"
          >
            <RefreshCwIcon className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <div className="p-2">
        {isLoadingDirectory ? (
          <div className="text-muted-foreground flex items-center justify-center gap-2 py-8 text-sm">
            <Loader2Icon className="h-4 w-4 animate-spin" />
            Loading...
          </div>
        ) : error ? (
          <div className="text-destructive py-8 text-center text-sm">
            {error}
          </div>
        ) : rootEntries.length === 0 ? (
          <div className="text-muted-foreground py-8 text-center text-sm">
            No files found in this directory
          </div>
        ) : (
          rootEntries.map((entry) => renderEntry(entry))
        )}
      </div>
    </div>
  );
}
