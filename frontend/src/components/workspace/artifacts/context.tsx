import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useSidebar } from "@/components/ui/sidebar";
import { browseDirectory, type DirectoryEntry } from "@/core/filesystem/api";
import { fetchThreadVariables } from "@/core/global-variables/api";
import { env } from "@/env";

export interface ArtifactsContextType {
  artifacts: string[];
  setArtifacts: (artifacts: string[]) => void;

  selectedArtifact: string | null;
  autoSelect: boolean;
  select: (artifact: string, autoSelect?: boolean) => void;
  deselect: () => void;
  backToList: () => void;

  open: boolean;
  autoOpen: boolean;
  setOpen: (open: boolean) => void;

  novelToc: string | null;
  rootPath: string | null;
  isLoadingNovelToc: boolean;

  directoryEntries: Record<string, DirectoryEntry[]>;
  expandedFolders: Set<string>;
  currentPath: string;
  isLoadingDirectory: boolean;
  directoryError: string | null;
  setDirectoryEntries: (path: string, entries: DirectoryEntry[]) => void;
  toggleFolder: (path: string) => void;
  loadDirectory: (path: string) => Promise<void>;
  loadFolderChildren: (path: string) => Promise<void>;
  expandAll: () => void;
  collapseAll: () => void;
  refreshDirectory: () => Promise<void>;
  navigateUp: () => void;
}

const ArtifactsContext = createContext<ArtifactsContextType | undefined>(
  undefined,
);

interface ArtifactsProviderProps {
  children: ReactNode;
  threadId: string;
}

export function ArtifactsProvider({
  children,
  threadId,
}: ArtifactsProviderProps) {
  const [artifacts, setArtifacts] = useState<string[]>([]);
  const [selectedArtifact, setSelectedArtifact] = useState<string | null>(null);
  const [autoSelect, setAutoSelect] = useState(true);
  const [open, setOpen] = useState(
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true",
  );
  const [autoOpen, setAutoOpen] = useState(true);
  const { setOpen: setSidebarOpen } = useSidebar();

  const [novelToc, setNovelToc] = useState<string | null>(null);
  const [isLoadingNovelToc, setIsLoadingNovelToc] = useState(true);

  const [directoryEntries, setDirectoryEntriesMap] = useState<
    Record<string, DirectoryEntry[]>
  >({});
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(
    new Set(),
  );
  const [currentPath, setCurrentPath] = useState("/mnt/user-data/workspace");
  const [isLoadingDirectory, setIsLoadingDirectory] = useState(false);
  const [directoryError, setDirectoryError] = useState<string | null>(null);

  const rootPath = novelToc;

  useEffect(() => {
    if (!threadId) return;
    setIsLoadingNovelToc(true);
    fetchThreadVariables(threadId)
      .then((data) => {
        const tocVar = data.variables.find((v) => v.key === "novel_toc");
        const toc = tocVar?.value ?? null;
        setNovelToc(toc);
      })
      .catch(() => {
        setNovelToc(null);
      })
      .finally(() => {
        setIsLoadingNovelToc(false);
      });
  }, [threadId]);

  const select = useCallback(
    (artifact: string, autoSelect = false) => {
      setSelectedArtifact(artifact);
      if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true") {
        setSidebarOpen(false);
      }
      if (!autoSelect) {
        setAutoSelect(false);
      }
    },
    [setSidebarOpen, setSelectedArtifact, setAutoSelect],
  );

  const deselect = useCallback(() => {
    setSelectedArtifact(null);
    setAutoSelect(true);
    setOpen(false);
  }, []);

  const backToList = useCallback(() => {
    setSelectedArtifact(null);
    setAutoSelect(true);
  }, []);

  const setDirectoryEntries = useCallback(
    (path: string, entries: DirectoryEntry[]) => {
      setDirectoryEntriesMap((prev) => ({ ...prev, [path]: entries }));
    },
    [],
  );

  const toggleFolder = useCallback((path: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  const loadDirectory = useCallback(
    async (path: string) => {
      setCurrentPath(path);
      setIsLoadingDirectory(true);
      setDirectoryError(null);
      try {
        const entries = await browseDirectory(threadId, path);
        setDirectoryEntries(path, entries);
        setExpandedFolders((prev) => {
          const next = new Set(prev);
          next.add(path);
          return next;
        });
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Failed to load directory";
        setDirectoryError(message);
        console.error("Failed to load directory:", error);
      } finally {
        setIsLoadingDirectory(false);
      }
    },
    [threadId, setDirectoryEntries],
  );

  const loadFolderChildren = useCallback(
    async (path: string) => {
      try {
        const entries = await browseDirectory(threadId, path);
        setDirectoryEntries(path, entries);
      } catch (error) {
        console.error("Failed to load folder children:", error);
      }
    },
    [threadId, setDirectoryEntries],
  );

  const expandAll = useCallback(() => {
    setDirectoryEntriesMap((prev) => {
      const next = new Set<string>();
      for (const [path, entries] of Object.entries(prev)) {
        if (entries.some((e) => e.isDirectory)) {
          next.add(path);
        }
        for (const entry of entries) {
          if (entry.isDirectory) {
            next.add(entry.path);
          }
        }
      }
      setExpandedFolders(next);
      return prev;
    });
  }, []);

  const collapseAll = useCallback(() => {
    setExpandedFolders(new Set());
  }, []);

  const refreshDirectory = useCallback(async () => {
    setDirectoryEntriesMap((prev) => {
      const paths = Object.keys(prev);
      void (async () => {
        await Promise.all(
          paths.map((path) =>
            browseDirectory(threadId, path)
              .then((entries) => {
                setDirectoryEntriesMap((curr) => ({
                  ...curr,
                  [path]: entries,
                }));
              })
              .catch(() => {
                /* ignore refresh errors */
              }),
          ),
        );
      })();
      return prev;
    });
  }, [threadId]);

  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!novelToc) return;
    refreshTimerRef.current = setInterval(() => {
      void refreshDirectory();
    }, 30_000);
    return () => {
      if (refreshTimerRef.current) {
        clearInterval(refreshTimerRef.current);
      }
    };
  }, [novelToc, refreshDirectory]);

  const navigateUp = useCallback(() => {
    const parent = currentPath.substring(0, currentPath.lastIndexOf("/"));
    if (
      parent &&
      (!rootPath || parent === rootPath || parent.startsWith(rootPath + "/"))
    ) {
      void loadDirectory(parent);
    }
  }, [currentPath, loadDirectory, rootPath]);

  const value: ArtifactsContextType = {
    artifacts,
    setArtifacts,

    open,
    autoOpen,
    autoSelect,
    setOpen: (isOpen: boolean) => {
      if (!isOpen && autoOpen) {
        setAutoOpen(false);
        setAutoSelect(false);
      }
      setOpen(isOpen);
    },

    selectedArtifact,
    select,
    deselect,
    backToList,

    novelToc,
    rootPath,
    isLoadingNovelToc,

    directoryEntries,
    expandedFolders,
    currentPath,
    isLoadingDirectory,
    directoryError,
    setDirectoryEntries,
    toggleFolder,
    loadDirectory,
    loadFolderChildren,
    expandAll,
    collapseAll,
    refreshDirectory,
    navigateUp,
  };

  return (
    <ArtifactsContext.Provider value={value}>
      {children}
    </ArtifactsContext.Provider>
  );
}

export function useArtifacts() {
  const context = useContext(ArtifactsContext);
  if (context === undefined) {
    throw new Error("useArtifacts must be used within an ArtifactsProvider");
  }
  return context;
}
