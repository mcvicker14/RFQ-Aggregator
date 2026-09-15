"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { tasksApi } from "@/lib/api/resources";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PriorityBadge, TaskStatusBadge } from "@/components/domain/badges";
import { LoadingState, ErrorState, EmptyState } from "@/components/ui/states";
import { formatDate, cn, daysUntil } from "@/lib/utils";
import type { Task } from "@/types";

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("open");

  function load() {
    setError(null);
    tasksApi
      .list(statusFilter === "all" ? {} : { status: statusFilter })
      .then(setTasks)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [statusFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  async function toggle(task: Task) {
    await tasksApi.update(task.id, { status: task.status === "completed" ? "open" : "completed" });
    load();
  }

  if (error) return <ErrorState message={error} onRetry={load} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Tasks</h1>
          <p className="text-sm text-muted-foreground">Business-development follow-ups across the pipeline.</p>
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="open">Open</SelectItem>
            <SelectItem value="in_progress">In Progress</SelectItem>
            <SelectItem value="completed">Completed</SelectItem>
            <SelectItem value="all">All</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardContent className="p-0">
          {!tasks ? (
            <LoadingState />
          ) : tasks.length === 0 ? (
            <EmptyState title="No tasks" description="Nothing matches this filter." className="border-0" />
          ) : (
            <ul className="divide-y divide-border">
              {tasks.map((task) => {
                const due = daysUntil(task.due_date);
                return (
                  <li key={task.id} className="flex items-center justify-between gap-3 px-4 py-3">
                    <div className="flex items-center gap-3">
                      <input
                        type="checkbox"
                        checked={task.status === "completed"}
                        onChange={() => toggle(task)}
                        className="h-4 w-4 rounded border-input"
                      />
                      <div>
                        <div className={cn("text-sm", task.status === "completed" ? "text-muted-foreground line-through" : "text-foreground")}>
                          {task.title}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {task.opportunity_id ? (
                            <Link href={`/opportunities/${task.opportunity_id}`} className="hover:underline">
                              {task.opportunity_title}
                            </Link>
                          ) : (
                            "General"
                          )}
                          {" · Due "}
                          <span className={due !== null && due < 0 && task.status !== "completed" ? "font-medium text-destructive" : ""}>
                            {formatDate(task.due_date)}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <PriorityBadge value={task.priority} />
                      <TaskStatusBadge value={task.status} />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
