"use client";

import { useEffect } from "react";
import { track } from "@/lib/api";

export function TrackView({ name, props }: { name: string; props?: Record<string, string> }) {
  useEffect(() => {
    track(name, props);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}
