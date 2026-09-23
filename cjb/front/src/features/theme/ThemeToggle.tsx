import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Check, Monitor, Moon, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useTheme, type ThemeMode } from "@/features/theme/themeContext";

const OPTIONS: Array<{
  mode: ThemeMode;
  label: string;
  icon: typeof Sun;
}> = [
  { mode: "light", label: "Light", icon: Sun },
  { mode: "dark", label: "Dark", icon: Moon },
  { mode: "system", label: "System", icon: Monitor },
];

export function ThemeToggle() {
  const { mode, resolvedTheme, setMode } = useTheme();
  const active = OPTIONS.find((option) => option.mode === mode) ?? OPTIONS[2];
  const ActiveIcon = active.icon;

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="min-w-9 px-2.5 sm:min-w-[108px] sm:justify-start"
          aria-label={`Theme: ${active.label}`}
          title={`Theme: ${active.label}`}
        >
          <ActiveIcon className="h-4 w-4" aria-hidden="true" />
          <span className="hidden sm:inline">{active.label}</span>
          <span className="sr-only">Resolved theme: {resolvedTheme}</span>
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          className={cn(
            "z-50 min-w-36 overflow-hidden rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-lg",
            "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
          )}
        >
          <DropdownMenu.RadioGroup value={mode} onValueChange={(value) => setMode(value as ThemeMode)}>
            {OPTIONS.map((option) => {
              const Icon = option.icon;
              return (
                <DropdownMenu.RadioItem
                  key={option.mode}
                  value={option.mode}
                  className={cn(
                    "relative flex cursor-default select-none items-center gap-2 rounded-sm py-2 pl-8 pr-2 text-sm outline-none",
                    "focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
                  )}
                >
                  <span className="absolute left-2 flex h-4 w-4 items-center justify-center">
                    <DropdownMenu.ItemIndicator>
                      <Check className="h-4 w-4" />
                    </DropdownMenu.ItemIndicator>
                  </span>
                  <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                  {option.label}
                </DropdownMenu.RadioItem>
              );
            })}
          </DropdownMenu.RadioGroup>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
