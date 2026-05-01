import { Check, ChevronsUpDown, Lock } from "lucide-react";
import { useState, useCallback, useMemo } from "react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

interface NovelTagSelectorProps {
  value?: string;
  onChange: (tag: string | undefined) => void;
  tags: string[];
  locked?: boolean;
  isLoading?: boolean;
  error?: Error | null;
}

export function NovelTagSelector({
  value,
  onChange,
  tags,
  locked = false,
  isLoading = false,
  error = null,
}: NovelTagSelectorProps) {
  const [open, setOpen] = useState(false);

  const extractNovelName = (path: string) => {
    const segments = path.split("/").filter(Boolean);
    return segments[segments.length - 1] ?? path;
  };

  const handleSelect = useCallback(
    (tag: string) => {
      onChange(tag === value ? undefined : tag);
      setOpen(false);
    },
    [onChange, value],
  );

  const selectedTag = useMemo(
    () => tags.find((tag) => tag === value),
    [tags, value],
  );

  if (locked && value) {
    return (
      <Button
        variant="outline"
        className="w-full cursor-not-allowed justify-between opacity-60"
        disabled
      >
        <span className="flex items-center gap-1.5">
          <Lock className="h-3.5 w-3.5" />
          {extractNovelName(value)}
        </span>
      </Button>
    );
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="w-full justify-between"
          disabled={isLoading}
        >
          {selectedTag ? extractNovelName(selectedTag) : "选择所属小说（可选）"}
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-full p-0" align="start">
        <Command>
          <CommandInput placeholder="搜索小说..." />
          <CommandList>
            <CommandEmpty>
              {isLoading
                ? "加载中..."
                : error
                  ? "加载失败，请重试"
                  : "没有找到小说"}
            </CommandEmpty>
            <CommandGroup>
              {tags.map((tag) => (
                <CommandItem
                  key={tag}
                  value={tag}
                  onSelect={() => handleSelect(tag)}
                >
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4",
                      value === tag ? "opacity-100" : "opacity-0",
                    )}
                  />
                  {extractNovelName(tag)}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
