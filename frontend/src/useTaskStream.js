import { useEffect, useRef, useState } from "react";
import { getResearchTask } from "./api";

function appendEvent(events, event) {
  return [...events.slice(-199), event];
}

function eventMessage(event) {
  const { type, data = {} } = event;

  if (type === "snapshot") {
    return `状态同步：${data.status} / ${data.current_stage}`;
  }
  if (type === "status") {
    return `状态更新：${data.status}`;
  }
  if (type === "stage") {
    const stage = data.stage || "unknown";
    return `阶段切换：${stage}`;
  }
  if (type === "progress") {
    return `研究进度：${data.completed_sections ?? 0}/${data.planned_sections ?? "?"}`;
  }
  if (type === "plan_review_required") {
    return "研究计划已生成，等待人工确认";
  }
  if (type === "report_start") {
    return "报告正文开始输出";
  }
  if (type === "report_end") {
    return "报告正文输出完成";
  }
  if (type === "poll") {
    return `轮询状态：${data.status} / ${data.current_stage}`;
  }
  return `事件：${type}`;
}

export function useTaskStream(taskId) {
  const [task, setTask] = useState(null);
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);
  const [reportText, setReportText] = useState("");
  const lastStatusRef = useRef("");

  useEffect(() => {
    if (!taskId) {
      setTask(null);
      setEvents([]);
      setConnected(false);
      setError(null);
      setReportText("");
      return undefined;
    }

    let cancelled = false;
    let eventSource;

    async function refresh() {
      try {
        const nextTask = await getResearchTask(taskId);
        if (cancelled) return;

        const nextStatus = nextTask.status;
        if (lastStatusRef.current && lastStatusRef.current !== nextStatus) {
          setEvents((current) =>
            appendEvent(current, {
              type: "poll",
              data: {
                status: nextStatus,
                current_stage: nextTask.current_stage,
              },
            }),
          );
        }
        lastStatusRef.current = nextStatus;
        setTask(nextTask);
        setError(null);
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    }

    refresh();
    const pollId = window.setInterval(refresh, 2500);

    try {
      eventSource = new EventSource(
        `/api/v1/research-tasks/${taskId}/events`,
      );

      eventSource.onopen = () => {
        if (!cancelled) setConnected(true);
      };

      eventSource.onmessage = (message) => {
        if (cancelled) return;
        try {
          const event = JSON.parse(message.data);

          if (event.type === "report_start") {
            setReportText("");
            setEvents((current) => appendEvent(current, event));
          } else if (event.type === "report_delta") {
            setReportText(
              (current) => current + (event.data?.text || ""),
            );
          } else {
            setEvents((current) => appendEvent(current, event));
          }

          if (event.type === "snapshot" || event.type === "status") {
            setTask((current) =>
              current
                ? {
                    ...current,
                    status: event.data.status ?? current.status,
                    current_stage:
                      event.data.current_stage ?? current.current_stage,
                    progress: event.data.progress ?? current.progress,
                  }
                : current,
            );
          }
          if (event.type === "stage") {
            setTask((current) =>
              current
                ? {
                    ...current,
                    current_stage: event.data.stage,
                  }
                : current,
            );
          }
          if (event.type === "progress") {
            setTask((current) =>
              current
                ? { ...current, progress: event.data }
                : current,
            );
          }
        } catch (err) {
          setEvents((current) =>
            appendEvent(current, {
              type: "parse_error",
              data: { message: err.message },
            }),
          );
        }
      };

      eventSource.onerror = () => {
        if (!cancelled) setConnected(false);
      };
    } catch (err) {
      if (!cancelled) setConnected(false);
    }

    return () => {
      cancelled = true;
      window.clearInterval(pollId);
      if (eventSource) eventSource.close();
    };
  }, [taskId]);

  return { task, events, connected, error, reportText };
}

export { eventMessage };
