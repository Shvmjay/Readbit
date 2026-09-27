import { Award, BookOpen, Flag, Flame, Lock, RefreshCw, ScrollText, Sparkles, Star, Target, Trophy } from "lucide-react";
import clsx from "clsx";
import type { Achievement } from "@/lib/types";

const ICONS: Record<string, typeof Award> = { book: BookOpen, scroll: ScrollText, sparkle: Sparkles, star: Star, flag: Flag, target: Target, refresh: RefreshCw, flame: Flame, trophy: Trophy };

export function AchievementCard({ a, lockedLabel }: { a: Achievement; lockedLabel: string }) {
  const Icon = ICONS[a.icon_key] ?? Award;
  return (
    <li className={clsx("card flex items-start gap-3 p-4", !a.earned && "opacity-60")} data-testid={`achievement-${a.code}`} data-earned={a.earned}>
      <span className={clsx("rounded-xl p-2", a.earned ? "bg-accent text-accent-ink" : "bg-line/60 text-muted")}>
        {a.earned ? <Icon className="h-5 w-5" aria-hidden /> : <Lock className="h-5 w-5" aria-hidden />}
      </span>
      <div>
        <p className="font-medium">{a.name}</p>
        <p className="text-sm text-muted">{a.description}</p>
        {!a.earned && <p className="mt-1 text-xs text-muted">{lockedLabel}</p>}
      </div>
    </li>
  );
}
