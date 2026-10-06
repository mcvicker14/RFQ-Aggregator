"use client";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { StatusBoardWorkspace } from "@/components/status-board/status-board-workspace";
import { LoadingState } from "@/components/ui/states";
import type { StatusBoardFilterName } from "@/types";
function Board() {
  const params = useSearchParams();
  return <StatusBoardWorkspace initialFilter={(params.get("filter") as StatusBoardFilterName) || "all_active"} />;
}
export default function StatusBoardPage() {
  return <Suspense fallback={<LoadingState />}><Board /></Suspense>;
}
