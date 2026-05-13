import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { getNovelCard, listChapterFiles } from "@/core/api/sessions";
import {
  setThreadVariable,
  deleteThreadVariable,
  fetchThreadVariables,
} from "@/core/global-variables/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface NovelCardData {
  book_name: string;
  genre: string;
  concept: string;
  platform: string;
  status: string;
  current_chapter: number;
  target_chapters: number;
  created_at: string;
}

export interface MonitorConfig {
  idleTimeoutMinutes: number; // default 10
}

export interface MonitorState {
  enabled: boolean;
  config: MonitorConfig;
  dialogOpen: boolean;
  cardPath: string; // display path (without /mnt prefix)
  currentChapter: number;
  targetChapters: number;
  // Validation state
  novelTocSet: boolean; // whether novel_toc is configured
  cardJsonExists: boolean; // whether card.json exists
  validationError: string; // error message if validation fails
  // File-based chapter detection
  detectedChapters: number[]; // chapter numbers found in 02-正文/
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_STOP_WINDOW_MS = 2 * 60 * 1000; // 2 minutes
const STOP_COUNT_THRESHOLD = 3; // 3 consecutive fast stops
const PAUSE_RETRY_MS = 10 * 60 * 1000; // 10 minutes
const MAX_RETRY_ROUNDS = 1; // 1 retry round then permanent stop
const CARD_REFRESH_INTERVAL_MS = 30_000; // 30 seconds

// ---------------------------------------------------------------------------
// Build resume prompt
// ---------------------------------------------------------------------------

function buildResumePrompt(
  detectedChapters: number[],
  targetChapters: number,
): string {
  const detectedStr =
    detectedChapters.length > 0
      ? detectedChapters.map((c) => `第${c}章`).join(", ")
      : "无";

  return (
    `<system_notification>\n` +
    `【自动续传监控】你正在被自动续传系统监控。本次任务由系统自动触发，目的是确保写作计划被完整执行。\n\n` +
    `【用户计划】目标完成到第${targetChapters}章。请严格按照步骤逐章写作，调用工作流写作，直到完成全部计划章节。不要中途自行停止。\n\n` +
    `【执行流程】处理长任务（一次写多章节）时，请按照以下步骤循环执行：\n` +
    `依次调用writing工作流，直到完成全部计划章节，禁止直接写作。\n\n` +
    `若还没有生成正文规划（02-正文\第n-m章\_task\写作任务汇总.md）则调用整理工作流（organize），禁止直接写作。\n\n` +
    `【判断条件】系统通过扫描 02-正文 目录下的文件来判断进度。当前已识别到的章节文件：${detectedStr}。\n` +
    `系统要求在目标章节附近至少识别到 5 个章节文件才算完成。\n\n` +
    `⚠️ 重要：请确保每章文件名严格使用「第N章.md」格式（N为章节号，纯数字，无多余空格）。\n` +
    `   如果你已经写完所有章节但系统仍在监控，请自行检查文件名是否符合规范。\n` +
    `</system_notification>`
  );
}

// ---------------------------------------------------------------------------
// Per-thread runtime
// ---------------------------------------------------------------------------

interface ThreadRuntime {
  enabled: boolean;
  config: MonitorConfig;
  stopTimes: number[];
  errorStage: "idle" | "paused" | "stopped";
  retryRound: number;
  idleTimerId: ReturnType<typeof setTimeout> | null;
  retryTimerId: ReturnType<typeof setTimeout> | null;
  cardRefreshTimerId: ReturnType<typeof setInterval> | null;
  novelToc: string; // "/mnt/shared-data/..."
  getIsLoading: () => boolean;
  doSendMessage: (msg: string) => Promise<void>;
}

const runtimes = new Map<string, ThreadRuntime>();

function getRuntime(threadId: string): ThreadRuntime {
  let rt = runtimes.get(threadId);
  if (!rt) {
    rt = {
      enabled: false,
      config: { idleTimeoutMinutes: 10 },
      stopTimes: [],
      errorStage: "idle",
      retryRound: 0,
      idleTimerId: null,
      retryTimerId: null,
      cardRefreshTimerId: null,
      novelToc: "",
      getIsLoading: () => false,
      doSendMessage: async () => {
        // placeholder
      },
    };
    runtimes.set(threadId, rt);
  }
  return rt;
}

// ---------------------------------------------------------------------------
// Core logic: called immediately when run stops (isLoading: true → false)
// ---------------------------------------------------------------------------

function hasRequiredChapters(detected: number[], target: number): boolean {
  const requiredCount = Math.min(5, target);
  const start = Math.max(1, target - requiredCount + 1);
  let found = 0;
  for (let ch = start; ch <= target; ch++) {
    if (detected.includes(ch)) found++;
  }
  return found >= requiredCount;
}

// ---------------------------------------------------------------------------
// Core logic: called immediately when run stops (isLoading: true → false)
// ---------------------------------------------------------------------------

async function onRunStopped(rt: ThreadRuntime, threadId: string) {
  if (!rt.enabled || rt.errorStage === "stopped") return;
  if (!rt.novelToc) return;

  // 1. Read card.json for target_chapters
  let card: NovelCardData;
  try {
    card = await getNovelCard(threadId, rt.novelToc);
  } catch {
    toast.warning("监控：读取 card.json 失败，将在下次停止时重试");
    return;
  }

  // 2. Scan chapter files
  let detected: number[];
  try {
    detected = await listChapterFiles(threadId, rt.novelToc);
  } catch {
    detected = [];
  }

  // 3. Should we resume? Check if last 5 chapters before target are present
  if (hasRequiredChapters(detected, card.target_chapters)) {
    toast.info(
      `监控：已检测到目标章节（第${card.target_chapters}章附近），无需续传`,
    );
    return;
  }

  // 4. Notify user that we detected a stop and will wait
  const timeoutMs = rt.config.idleTimeoutMinutes * 60 * 1000;
  const missing: number[] = [];
  const requiredCount = Math.min(5, card.target_chapters);
  const start = Math.max(1, card.target_chapters - requiredCount + 1);
  for (let ch = start; ch <= card.target_chapters; ch++) {
    if (!detected.includes(ch)) missing.push(ch);
  }
  toast.info(
    `监控：任务已停止，缺少章节 ${missing.length > 0 ? missing.map((c) => `第${c}章`).join(", ") : "（未识别）"}，` +
      `${rt.config.idleTimeoutMinutes} 分钟后自动续传`,
    { duration: 15000 },
  );

  rt.idleTimerId = setTimeout(async () => {
    if (!rt.enabled) return;
    if (rt.getIsLoading()) return;

    // Re-read card.json to get latest target
    let latestCard: NovelCardData;
    try {
      latestCard = await getNovelCard(threadId, rt.novelToc);
    } catch {
      toast.warning("监控：续传前读取 card.json 失败，跳过本次续传");
      return;
    }

    // Re-scan chapter files
    let latestDetected: number[];
    try {
      latestDetected = await listChapterFiles(threadId, rt.novelToc);
    } catch {
      latestDetected = [];
    }

    // Check again if resume is still needed
    if (hasRequiredChapters(latestDetected, latestCard.target_chapters)) {
      toast.info("监控：续传前检查发现章节已齐全，取消续传");
      return;
    }

    const prompt = buildResumePrompt(
      latestDetected,
      latestCard.target_chapters,
    );
    try {
      toast.success("监控：正在发送续传消息...");
      await rt.doSendMessage(prompt);
    } catch (err) {
      toast.error(
        `监控：续传消息发送失败 - ${err instanceof Error ? err.message : "未知错误"}`,
      );
      rt.stopTimes.push(Date.now());
      maybeHandleErrorPattern(rt, threadId);
    }
  }, timeoutMs);
}

function maybeHandleErrorPattern(rt: ThreadRuntime, threadId: string) {
  const now = Date.now();
  const recent = rt.stopTimes.filter((t) => now - t <= MAX_STOP_WINDOW_MS * 2);
  rt.stopTimes = recent;

  if (recent.length >= STOP_COUNT_THRESHOLD) {
    const firstInWindow = recent[recent.length - STOP_COUNT_THRESHOLD]!;
    const lastInWindow = recent[recent.length - 1]!;
    if (lastInWindow - firstInWindow <= MAX_STOP_WINDOW_MS) {
      if (rt.retryRound < MAX_RETRY_ROUNDS) {
        rt.enabled = false;
        rt.errorStage = "paused";
        rt.retryRound += 1;
        if (rt.idleTimerId) {
          clearTimeout(rt.idleTimerId);
          rt.idleTimerId = null;
        }
        if (rt.cardRefreshTimerId) {
          clearInterval(rt.cardRefreshTimerId);
          rt.cardRefreshTimerId = null;
        }
        toast.warning(
          `LLM 接口持续报错，监控暂停，${PAUSE_RETRY_MS / 60000} 分钟后重试`,
        );
        rt.retryTimerId = setTimeout(() => {
          rt.enabled = true;
          rt.errorStage = "idle";
          rt.stopTimes = [];
          rt.retryTimerId = null;
        }, PAUSE_RETRY_MS);
      } else {
        rt.enabled = false;
        rt.errorStage = "stopped";
        if (rt.idleTimerId) {
          clearTimeout(rt.idleTimerId);
          rt.idleTimerId = null;
        }
        if (rt.cardRefreshTimerId) {
          clearInterval(rt.cardRefreshTimerId);
          rt.cardRefreshTimerId = null;
        }
        toast.error("LLM 接口持续报错，监控已自动关闭");
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAutoResumeMonitor(
  threadId: string | undefined | null,
  novelToc: string | undefined | null,
  getIsLoading: () => boolean,
  doSendMessage: (msg: string) => Promise<void>,
) {
  const [monitorState, setMonitorState] = useState<MonitorState>({
    enabled: false,
    config: { idleTimeoutMinutes: 10 },
    dialogOpen: false,
    cardPath: "",
    currentChapter: 0,
    targetChapters: 0,
    novelTocSet: false,
    cardJsonExists: false,
    validationError: "",
    detectedChapters: [],
  });

  const getIsLoadingRef = useRef(getIsLoading);
  const doSendMessageRef = useRef(doSendMessage);
  const novelTocRef = useRef(novelToc ?? "");

  useEffect(() => {
    getIsLoadingRef.current = getIsLoading;
  }, [getIsLoading]);
  useEffect(() => {
    doSendMessageRef.current = doSendMessage;
  }, [doSendMessage]);
  useEffect(() => {
    novelTocRef.current = novelToc ?? "";
  }, [novelToc]);

  // Register / unregister runtime
  useEffect(() => {
    if (!threadId) return;
    const rt = getRuntime(threadId);
    rt.getIsLoading = () => getIsLoadingRef.current();
    rt.doSendMessage = (msg: string) => doSendMessageRef.current(msg);
    rt.novelToc = novelTocRef.current;
    return () => {
      if (rt.idleTimerId) clearTimeout(rt.idleTimerId);
      if (rt.retryTimerId) clearTimeout(rt.retryTimerId);
      if (rt.cardRefreshTimerId) clearInterval(rt.cardRefreshTimerId);
      runtimes.delete(threadId);
    };
  }, [threadId]);

  // Event-driven: detect isLoading true→false transition
  const prevLoadingRef = useRef(false);

  // Restore monitor state from persisted global variable on mount
  const restoredRef = useRef(false);
  useEffect(() => {
    if (!threadId || !novelToc || restoredRef.current) return;
    restoredRef.current = true;

    const rt = getRuntime(threadId);
    if (rt.enabled) return;

    fetchThreadVariables(threadId)
      .then((data) => {
        const monitorVar = data.variables.find(
          (v) => v.key === "_monitor_enabled",
        );
        if (monitorVar?.value === "true") {
          const cardPath = novelToc.replace(/^\/mnt/, "") + "/card.json";

          rt.novelToc = novelToc;

          setMonitorState((prev) => ({
            ...prev,
            enabled: true,
            cardPath,
          }));

          // Sync prevLoadingRef with current state so next transition is detected
          const currentLoading = getIsLoadingRef.current();
          prevLoadingRef.current = currentLoading;

          // If task is already idle when monitor is restored, trigger a check
          if (!currentLoading) {
            setTimeout(() => {
              if (rt.enabled && !rt.getIsLoading()) {
                void onRunStopped(rt, threadId);
              }
            }, 2000);
          }
        }
      })
      .catch(() => {
        // Silently ignore - monitor was not previously enabled
      });
  }, [threadId, novelToc]);

  // Visibility change: when user switches back to this tab, check if resume needed
  useEffect(() => {
    if (!threadId) return;

    const handleVisibilityChange = () => {
      if (document.hidden) return;
      const rt = getRuntime(threadId);
      if (!rt.enabled) return;
      if (rt.getIsLoading()) return;

      // Sync prevLoadingRef with current state
      prevLoadingRef.current = false;

      // Task is idle and monitor is active - check if we need to resume
      void onRunStopped(rt, threadId);
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [threadId]);

  // Sync React state → runtime
  useEffect(() => {
    if (!threadId) return;
    const rt = getRuntime(threadId);
    rt.enabled = monitorState.enabled;
    rt.config = monitorState.config;
  }, [threadId, monitorState]);

  // Card refresh loop (every 30s when monitoring, with immediate first read)
  useEffect(() => {
    if (!threadId || !novelToc) return;
    const rt = getRuntime(threadId);

    if (monitorState.enabled && !rt.cardRefreshTimerId) {
      const doRefresh = async () => {
        try {
          const card = await getNovelCard(threadId, rt.novelToc);
          let detected: number[] = [];
          try {
            detected = await listChapterFiles(threadId, rt.novelToc);
          } catch {
            // ignore scan errors
          }
          setMonitorState((prev) => ({
            ...prev,
            currentChapter: card.current_chapter,
            targetChapters: card.target_chapters,
            cardJsonExists: true,
            detectedChapters: detected,
          }));
        } catch {
          // ignore refresh errors
        }
      };

      void doRefresh();
      rt.cardRefreshTimerId = setInterval(
        () => void doRefresh(),
        CARD_REFRESH_INTERVAL_MS,
      );
    } else if (!monitorState.enabled && rt.cardRefreshTimerId) {
      clearInterval(rt.cardRefreshTimerId);
      rt.cardRefreshTimerId = null;
    }
  }, [threadId, novelToc, monitorState.enabled]);

  // Event-driven: detect isLoading true→false transition
  useEffect(() => {
    if (!threadId) return;
    const rt = getRuntime(threadId);
    const isLoading = getIsLoadingRef.current();

    if (prevLoadingRef.current && !isLoading) {
      void onRunStopped(rt, threadId);
    }

    if (!prevLoadingRef.current && isLoading && rt.idleTimerId) {
      clearTimeout(rt.idleTimerId);
      rt.idleTimerId = null;
    }

    prevLoadingRef.current = isLoading;
  }, [threadId, getIsLoading()]);

  // Track error pattern on stop
  const [stopTick, setStopTick] = useState(0);
  useEffect(() => {
    if (!threadId) return;
    const isLoading = getIsLoadingRef.current();
    if (!isLoading && prevLoadingRef.current) {
      const rt = getRuntime(threadId);
      rt.stopTimes.push(Date.now());
      const now = Date.now();
      rt.stopTimes = rt.stopTimes.filter(
        (t) => now - t <= MAX_STOP_WINDOW_MS * 2,
      );
      maybeHandleErrorPattern(rt, threadId);
    }
  }, [threadId, getIsLoading(), stopTick]);

  // Sync novelToc availability to state
  useEffect(() => {
    const isSet = Boolean(novelToc);
    setMonitorState((prev) => {
      if (prev.novelTocSet === isSet) return prev;
      return { ...prev, novelTocSet: isSet };
    });
  }, [novelToc]);

  // -----------------------------------------------------------------------
  // Public actions
  // -----------------------------------------------------------------------

  const openDialog = useCallback(() => {
    // Validate novel_toc
    if (!novelToc) {
      setMonitorState((prev) => ({
        ...prev,
        dialogOpen: true,
        novelTocSet: false,
        cardJsonExists: false,
        validationError: "未设置小说路径，无法监控",
      }));
      return;
    }

    const cardPath = novelToc.replace(/^\/mnt/, "") + "/card.json";
    setMonitorState((prev) => ({
      ...prev,
      dialogOpen: true,
      cardPath,
      novelTocSet: true,
      validationError: "",
    }));

    // Try to read card.json and scan chapter files
    getNovelCard(threadId!, novelToc)
      .then((card) => {
        setMonitorState((prev) => ({
          ...prev,
          currentChapter: card.current_chapter,
          targetChapters: card.target_chapters,
          cardJsonExists: true,
        }));
        return listChapterFiles(threadId!, novelToc);
      })
      .then((detected) => {
        setMonitorState((prev) => ({
          ...prev,
          detectedChapters: detected,
        }));
      })
      .catch(() => {
        setMonitorState((prev) => ({
          ...prev,
          cardJsonExists: false,
          validationError: "card.json 不存在，无法监控",
        }));
      });
  }, [threadId, novelToc]);

  const closeDialog = useCallback(() => {
    setMonitorState((prev) => ({ ...prev, dialogOpen: false }));
  }, []);

  const updateConfig = useCallback((config: Partial<MonitorConfig>) => {
    setMonitorState((prev) => ({
      ...prev,
      config: { ...prev.config, ...config },
    }));
  }, []);

  const startMonitor = useCallback(() => {
    if (!threadId || !novelToc) return;
    const rt = getRuntime(threadId);
    rt.novelToc = novelToc;
    rt.errorStage = "idle";
    rt.retryRound = 0;
    rt.stopTimes = [];

    const cardPath = novelToc.replace(/^\/mnt/, "") + "/card.json";

    setMonitorState((prev) => ({
      ...prev,
      cardPath,
      enabled: true,
      dialogOpen: false,
      validationError: "",
    }));

    // Read initial card state and scan chapter files
    getNovelCard(threadId, novelToc)
      .then((card) => {
        setMonitorState((prev) => ({
          ...prev,
          currentChapter: card.current_chapter,
          targetChapters: card.target_chapters,
          cardJsonExists: true,
        }));
        return listChapterFiles(threadId, novelToc);
      })
      .then((detected) => {
        setMonitorState((prev) => ({
          ...prev,
          detectedChapters: detected,
        }));
      })
      .catch(() => {
        // Keep monitoring enabled even if card read fails initially
      });

    // Persist monitor state to thread-level global variable
    setThreadVariable(threadId, "_monitor_enabled", {
      value: "true",
      description: "Auto-resume monitor enabled state",
      llm_editable: false,
    }).catch(() => {
      // Silently ignore persistence errors
    });

    toast.success("监控已启动");
  }, [threadId, novelToc]);

  const stopMonitor = useCallback(
    (permanent = false) => {
      if (!threadId) return;
      const rt = getRuntime(threadId);
      if (rt.idleTimerId) {
        clearTimeout(rt.idleTimerId);
        rt.idleTimerId = null;
      }
      if (rt.retryTimerId) {
        clearTimeout(rt.retryTimerId);
        rt.retryTimerId = null;
      }
      if (rt.cardRefreshTimerId) {
        clearInterval(rt.cardRefreshTimerId);
        rt.cardRefreshTimerId = null;
      }
      rt.enabled = false;
      rt.errorStage = permanent ? "stopped" : "idle";
      rt.retryRound = 0;
      rt.stopTimes = [];

      setMonitorState((prev) => ({
        ...prev,
        enabled: false,
        dialogOpen: false,
        cardPath: "",
        currentChapter: 0,
        targetChapters: 0,
        detectedChapters: [],
      }));

      // Remove monitor state from thread-level global variable
      deleteThreadVariable(threadId, "_monitor_enabled").catch(() => {
        // Silently ignore persistence errors
      });

      if (permanent) {
        toast.error("监控已自动关闭（LLM 接口持续报错）");
      } else {
        toast.info("监控已停止");
      }
    },
    [threadId],
  );

  // Sync back when errorStage changes externally
  useEffect(() => {
    if (!threadId) return;
    const rt = getRuntime(threadId);
    if (
      !rt.enabled &&
      (rt.errorStage === "stopped" || rt.errorStage === "paused") &&
      monitorState.enabled
    ) {
      setMonitorState((prev) => ({ ...prev, enabled: false }));
    }
    const id = setInterval(() => setStopTick((t) => t + 1), 5000);
    return () => clearInterval(id);
  }, [threadId]);

  return {
    monitorState,
    openDialog,
    closeDialog,
    updateConfig,
    startMonitor,
    stopMonitor,
  };
}

// ---------------------------------------------------------------------------
// Exported for testing
// ---------------------------------------------------------------------------

export const _TEST_CONSTANTS = {
  MAX_STOP_WINDOW_MS,
  STOP_COUNT_THRESHOLD,
  PAUSE_RETRY_MS,
  MAX_RETRY_ROUNDS,
} as const;

export function _testBuildResumePrompt(
  detectedChapters: number[],
  targetChapters: number,
): string {
  return buildResumePrompt(detectedChapters, targetChapters);
}

export function _testShouldResume(detected: number[], target: number): boolean {
  return !hasRequiredChapters(detected, target);
}

export function _testHasRequiredChapters(
  detected: number[],
  target: number,
): boolean {
  return hasRequiredChapters(detected, target);
}

export function _testDetectErrorPattern(stopTimes: number[]): {
  detected: boolean;
  shouldPause: boolean;
  shouldStop: boolean;
  retryRound: number;
} {
  const now = Date.now();
  const recent = stopTimes.filter((t) => now - t <= MAX_STOP_WINDOW_MS * 2);

  if (recent.length < STOP_COUNT_THRESHOLD) {
    return {
      detected: false,
      shouldPause: false,
      shouldStop: false,
      retryRound: 0,
    };
  }

  const firstInWindow = recent[recent.length - STOP_COUNT_THRESHOLD]!;
  const lastInWindow = recent[recent.length - 1]!;
  const inWindow = lastInWindow - firstInWindow <= MAX_STOP_WINDOW_MS;

  return {
    detected: inWindow,
    shouldPause: inWindow,
    shouldStop: false,
    retryRound: inWindow ? 1 : 0,
  };
}
