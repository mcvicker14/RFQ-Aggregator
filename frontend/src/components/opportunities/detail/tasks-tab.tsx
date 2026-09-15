"use client";

import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { tasksApi } from "@/lib/api/resources";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PriorityBadge, TaskStatusBadge } from "@/components/domain/badges";
import { LoadingState, ErrorState, EmptyState } from "@/components/ui/states";
import { formatDate } from "@/lib/utils";
import type { Task } from "@/types";

export function TasksTab({ opportunityId }: { opportunityId: string }) {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [priority, setPriority] = useState("medium");
  const [busy, setBusy] = useState(false);

  function load() {
    setError(null);
    tasksApi.listForOpportunity(opportunityId).then(setTasks).catch((e) => setError(e.message));
  }
  useEffect(load, [opportunityId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function addTask(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    try {
      await tasksApi.create({ title, due_date: dueDate || null, priority, status: "open" }, opportunityId);
      setTitle("");
      setDueDate("");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add task");
    } finally {
      setBusy(false);
    }
  }

  async function toggleComplete(task: Task) {
    await tasksApi.update(task.id, { status: task.status === "completed" ? "open" : "completed" });
    load();
  }

  if (error) return <ErrorState message={error} onRetry={load} />;

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-4">
        <form onSubmit={addTask} className="flex flex-wrap items-end gap-2">
          <div className="flex-1 min-w-[200px]">
            <Input placeholder="New task…" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <Input type="date" className="w-40" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
          <Select value={priority} onValueChange={setPriority}>
            <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="low">Low</SelectItem>
              <SelectItem value="medium">Medium</SelectItem>
              <SelectItem value="high">High</SelectItem>
              <SelectItem value="urgent">Urgent</SelectItem>
            </SelectContent>
          </Select>
          <Button type="submit" size="sm" disabled={busy}><Plus className="h-3.5 w-3.5" /> Add</Button>
        </form>

        {!tasks ? (
          <LoadingState />
        ) : tasks.length === 0 ? (
          <EmptyState title="No tasks yet" description="Add a follow-up task for this opportunity." />
        ) : (
          <ul className="divide-y divide-border">
            {tasks.map((task) => (
              <li key={task.id} className="flex items-center justify-between gap-3 py-2.5">
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={task.status === "completed"}
                    onChange={() => toggleComplete(task)}
                    className="h-4 w-4 rounded border-input"
                  />
                  <div>
                    <div className={task.status === "completed" ? "text-sm text-muted-foreground line-through" : "text-sm text-foreground"}>
                      {task.title}
                    </div>
                    <div className="text-xs text-muted-foreground">Due {formatDate(task.due_date)}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <PriorityBadge value={task.priority} />
                  <TaskStatusBadge value={task.status} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
