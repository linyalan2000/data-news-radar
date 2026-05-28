"use client";
import { useState } from "react";
import type { NewsQueryParams } from "@/lib/api";
import { useSettings } from "@/lib/settings";

interface Props {
  onChange: (params: NewsQueryParams) => void;
}

export function FilterBar({ onChange }: Props) {
  const [settings] = useSettings();
  const [activeLabel, setActiveLabel] = useState<string | null>(null);

  const handleLabelClick = (label: string | null) => {
    const next = label === activeLabel ? null : label;
    setActiveLabel(next);
    onChange(next ? { label: next } : {});
  };

  return (
    <div className="flex flex-wrap items-center gap-2 w-full">
      {settings.categories.map(({ key, label }) => (
        <button
          key={label}
          onClick={() => handleLabelClick(key)}
          aria-pressed={activeLabel === key}
          className={`md:flex-1 px-4 md:px-5 py-2 md:py-2.5 rounded-lg text-sm md:text-base font-medium border transition-all duration-200 ${
            activeLabel === key
              ? "bg-[#e94560] text-white border-[#e94560] shadow-sm"
              : "bg-white text-gray-600 border-gray-200 hover:border-[#e94560]/40 hover:text-[#e94560]"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
