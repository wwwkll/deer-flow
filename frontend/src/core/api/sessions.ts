import type { NovelCardData } from "@/hooks/use-auto-resume-monitor";

/**
 * Read the novel card (card.json) for a given thread.
 * Uses the novel_toc global variable to locate the exact card.json path.
 *
 * @param threadId - The thread ID
 * @param novelToc - The novel_toc value (e.g., "/mnt/shared-data/novels/book/暗巷守护者")
 * @returns Parsed card.json data
 */
export async function getNovelCard(
  threadId: string,
  novelToc: string,
): Promise<NovelCardData> {
  if (!novelToc) {
    throw new Error("novel_toc is not set for thread " + threadId);
  }

  const cardPath = `${novelToc}/card.json`;
  const response = await fetch(
    `/api/threads/${threadId}/filesystem/read?${new URLSearchParams({ path: cardPath })}`,
  );

  if (!response.ok) {
    throw new Error(`Failed to read ${cardPath}: ${response.statusText}`);
  }

  const data = await response.json();
  return JSON.parse(data.content) as NovelCardData;
}

/**
 * List chapter files in the novel's 02-正文 directory, scanning up to 2 levels deep.
 * Returns a deduplicated array of detected chapter numbers.
 *
 * @param threadId - The thread ID
 * @param novelToc - The novel_toc value
 * @returns Array of chapter numbers found (e.g., [96, 97, 98, 99, 100])
 */
export async function listChapterFiles(
  threadId: string,
  novelToc: string,
): Promise<number[]> {
  if (!novelToc) return [];

  const chapterRegex = /第\s*(\d+)\s*章/;
  const chapters = new Set<number>();

  async function browseDir(
    dirPath: string,
  ): Promise<{ name: string; path: string; isDirectory: boolean }[]> {
    const response = await fetch(
      `/api/threads/${threadId}/filesystem/browse?${new URLSearchParams({ path: dirPath })}`,
    );
    if (!response.ok) return [];
    const data = await response.json();
    return data.entries ?? [];
  }

  async function scanLevel(dirPath: string, depth: number) {
    const entries = await browseDir(dirPath);
    for (const entry of entries) {
      if (entry.isDirectory) {
        if (depth < 2) {
          await scanLevel(entry.path, depth + 1);
        }
      } else {
        const match = chapterRegex.exec(entry.name);
        if (match?.[1]) {
          chapters.add(parseInt(match[1], 10));
        }
      }
    }
  }

  const contentDir = `${novelToc}/02-正文`;
  await scanLevel(contentDir, 0);

  return [...chapters].sort((a, b) => a - b);
}

/**
 * Convert container path to display-friendly relative path.
 * e.g., "/mnt/shared-data/novels/book/暗巷守护者" → "/shared-data/novels/book/暗巷守护者"
 */
export function toDisplayPath(containerPath: string): string {
  return containerPath.replace(/^\/mnt/, "");
}
