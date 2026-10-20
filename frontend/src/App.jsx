import { useEffect, useMemo, useState } from "react";
import {
  createResearchTask,
  getArtifacts,
  getPlanReview,
  getResearchResult,
  submitPlanReview,
} from "./api";
import { eventMessage, useTaskStream } from "./useTaskStream";

const EMPTY_FORM = {
  query: "",
  model: "deepseek-chat",
  language: "简体中文",
  max_sections: 3,
  max_plan_revisions: 3,
  publish_formats: {
    markdown: true,
    pdf: true,
    docx: false,
  },
  include_human_feedback: false,
  follow_guidelines: false,
  guidelines: "",
  verbose: false,
};

const TERMINAL_STATUSES = new Set([
  "completed",
  "completed_with_warnings",
  "failed",
]);

function buildPayload(form) {
  const formats = Object.entries(form.publish_formats)
    .filter(([, enabled]) => enabled)
    .map(([format]) => format);

  if (!form.query.trim()) throw new Error("请填写研究问题。");
  if (!form.model.trim()) throw new Error("请填写模型名称。");
  if (formats.length === 0) throw new Error("请至少选择一种报告格式。");
  if (form.follow_guidelines && !form.guidelines.trim()) {
    throw new Error("启用写作指南时必须填写指南内容。");
  }

  return {
    query: form.query.trim(),
    model: form.model.trim(),
    source: "web",
    language: form.language.trim() || "English",
    max_sections: Number(form.max_sections),
    max_plan_revisions: Number(form.max_plan_revisions),
    publish_formats: form.publish_formats,
    include_human_feedback: form.include_human_feedback,
    follow_guidelines: form.follow_guidelines,
    guidelines: form.follow_guidelines
      ? form.guidelines
          .split("\n")
          .map((item) => item.trim())
          .filter(Boolean)
      : [],
    verbose: form.verbose,
  };
}

function StatusBadge({ status }) {
  const label = {
    queued: "排队中",
    running: "运行中",
    awaiting_plan_review: "等待计划审核",
    completed: "已完成",
    completed_with_warnings: "已完成但有警告",
    failed: "失败",
  }[status];

  return <span className={`status-badge status-${status}`}>{label || status}</span>;
}

function ProgressBar({ progress }) {
  const planned = progress?.planned_sections;
  const completed = progress?.completed_sections;
  const percent =
    Number.isFinite(planned) && planned > 0
      ? Math.min(100, Math.round(((completed || 0) / planned) * 100))
      : 0;

  return (
    <div className="progress-track">
      <div className="progress-fill" style={{ width: `${percent}%` }} />
    </div>
  );
}

export default function App() {
  const [form, setForm] = useState(EMPTY_FORM);
  const [taskId, setTaskId] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [appError, setAppError] = useState(null);
  const [planReview, setPlanReview] = useState(null);
  const [reviewDecision, setReviewDecision] = useState("accept");
  const [reviewFeedback, setReviewFeedback] = useState("");
  const [result, setResult] = useState(null);
  const [artifacts, setArtifacts] = useState([]);

  const { task, events, connected, error: streamError } =
    useTaskStream(taskId);

  const isTerminal = task ? TERMINAL_STATUSES.has(task.status) : false;
  const isReviewPending = task?.status === "awaiting_plan_review";

  useEffect(() => {
    if (!taskId || !isReviewPending || planReview) return undefined;

    let cancelled = false;
    getPlanReview(taskId)
      .then((data) => {
        if (!cancelled) setPlanReview(data);
      })
      .catch((err) => {
        if (!cancelled) setAppError(err.message);
      });

    return () => {
      cancelled = true;
    };
  }, [taskId, isReviewPending, planReview]);

  useEffect(() => {
    const completed =
      task?.status === "completed" ||
      task?.status === "completed_with_warnings";
    if (!taskId || !completed || result) return undefined;

    let cancelled = false;
    getResearchResult(taskId)
      .then((data) => {
        if (!cancelled) setResult(data);
      })
      .catch((err) => {
        if (!cancelled) setAppError(err.message);
      });

    getArtifacts(taskId)
      .then((data) => {
        if (!cancelled) setArtifacts(data.items || []);
      })
      .catch(() => {
        if (!cancelled) setArtifacts([]);
      });

    return () => {
      cancelled = true;
    };
  }, [taskId, task?.status, result]);

  const displayError = appError || streamError;
  const stageLabel = useMemo(() => {
    const labels = {
      initial_research: "初步研究",
      planning: "制定研究计划",
      human_review: "人工审核计划",
      section_research: "研究各章节",
      writing: "撰写报告",
      publishing: "发布报告文件",
      finished: "已完成",
    };
    return labels[task?.current_stage] || task?.current_stage || "等待任务";
  }, [task?.current_stage]);

  function updateField(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function updateFormat(key, value) {
    setForm((current) => ({
      ...current,
      publish_formats: {
        ...current.publish_formats,
        [key]: value,
      },
    }));
  }

  async function handleCreate(event) {
    event.preventDefault();
    setSubmitting(true);
    setAppError(null);
    setResult(null);
    setArtifacts([]);
    setPlanReview(null);
    setReviewDecision("accept");
    setReviewFeedback("");

    try {
      const created = await createResearchTask(buildPayload(form));
      setTaskId(created.id);
    } catch (err) {
      setAppError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleReviewSubmit() {
    setAppError(null);
    try {
      await submitPlanReview(
        taskId,
        reviewDecision,
        reviewDecision === "revise" ? reviewFeedback.trim() : null,
      );
      setPlanReview(null);
      setReviewDecision("accept");
      setReviewFeedback("");
    } catch (err) {
      setAppError(err.message);
    }
  }

  function resetTask() {
    setTaskId(null);
    setPlanReview(null);
    setResult(null);
    setArtifacts([]);
    setAppError(null);
  }

  return (
    <main className="page">
      <header className="page-header">
        <div>
          <h1>DS Reporter Console</h1>
          <p>输入研究问题，自动生成多章节报告。</p>
        </div>
        {taskId && (
          <button className="ghost-button" onClick={resetTask}>
            新建任务
          </button>
        )}
      </header>

      <section className="card form-card">
        <h2>研究任务</h2>
        <form onSubmit={handleCreate}>
          <label>
            研究问题
            <textarea
              value={form.query}
              onChange={(event) => updateField("query", event.target.value)}
              placeholder="例如：AI 是否处于炒作周期？"
              rows={3}
              required
            />
          </label>

          <div className="field-grid">
            <label>
              模型
              <input
                value={form.model}
                onChange={(event) => updateField("model", event.target.value)}
                required
              />
            </label>
            <label>
              报告语言
              <input
                value={form.language}
                onChange={(event) => updateField("language", event.target.value)}
              />
            </label>
            <label>
              最大章节数
              <input
                type="number"
                min="1"
                max="20"
                value={form.max_sections}
                onChange={(event) =>
                  updateField("max_sections", event.target.value)
                }
              />
            </label>
            <label>
              最大计划修订次数
              <input
                type="number"
                min="0"
                max="20"
                value={form.max_plan_revisions}
                onChange={(event) =>
                  updateField("max_plan_revisions", event.target.value)
                }
              />
            </label>
          </div>

          <fieldset>
            <legend>发布格式</legend>
            <div className="checkbox-row">
              {["markdown", "pdf", "docx"].map((format) => (
                <label key={format}>
                  <input
                    type="checkbox"
                    checked={form.publish_formats[format]}
                    onChange={(event) =>
                      updateFormat(format, event.target.checked)
                    }
                  />
                  {format}
                </label>
              ))}
            </div>
          </fieldset>

          <div className="checkbox-row">
            <label>
              <input
                type="checkbox"
                checked={form.include_human_feedback}
                onChange={(event) =>
                  updateField("include_human_feedback", event.target.checked)
                }
              />
              需要人工审核研究计划
            </label>
            <label>
              <input
                type="checkbox"
                checked={form.follow_guidelines}
                onChange={(event) =>
                  updateField("follow_guidelines", event.target.checked)
                }
              />
              遵循写作指南
            </label>
            <label>
              <input
                type="checkbox"
                checked={form.verbose}
                onChange={(event) => updateField("verbose", event.target.checked)}
              />
              详细日志
            </label>
          </div>

          {form.follow_guidelines && (
            <label>
              写作指南（每行一条）
              <textarea
                value={form.guidelines}
                onChange={(event) =>
                  updateField("guidelines", event.target.value)
                }
                placeholder="报告必须使用 APA 格式"
                rows={3}
              />
            </label>
          )}

          {displayError && <div className="error-box">{displayError}</div>}

          <button className="primary-button" disabled={submitting}>
            {submitting ? "创建中..." : "创建研究任务"}
          </button>
        </form>
      </section>

      {task && (
        <section className="card task-card">
          <div className="task-header">
            <div>
              <h2>{task.request?.query || form.query || "研究任务"}</h2>
              <p className="muted">Task ID: {taskId}</p>
            </div>
            <StatusBadge status={task.status} />
          </div>

          <div className="stage-row">
            <span>当前阶段：{stageLabel}</span>
            {!isTerminal && <span>自动刷新中</span>}
          </div>
          <ProgressBar progress={task.progress} />

          {task.error && (
            <div className="error-box">
              {task.error.code}: {task.error.message}
            </div>
          )}

          {isReviewPending && planReview && (
            <PlanReviewCard
              review={planReview}
              decision={reviewDecision}
              feedback={reviewFeedback}
              onDecisionChange={setReviewDecision}
              onFeedbackChange={setReviewFeedback}
              onSubmit={handleReviewSubmit}
            />
          )}

          {isTerminal && result && (
            <ReportView result={result} artifacts={artifacts} />
          )}
        </section>
      )}

      {taskId && (
        <section className="card stream-card">
          <div className="stream-header">
            <h2>流式事件</h2>
            <span className={connected ? "stream-online" : "stream-offline"}>
              {connected ? "SSE 已连接" : "SSE 未连接，使用轮询"}
            </span>
          </div>
          <div className="event-list">
            {events.length === 0 ? (
              <p className="muted">等待任务事件...</p>
            ) : (
              events.map((event, index) => (
                <div className="event-line" key={`${index}-${event.type}`}>
                  <span>{new Date().toLocaleTimeString()}</span>
                  <strong>{event.type}</strong>
                  <span>{eventMessage(event)}</span>
                </div>
              ))
            )}
          </div>
          {reportText && (
            <div className="report-section">
              <h4>报告流式输出</h4>
              <pre className="markdown-output stream-report-output">
                {reportText}
              </pre>
            </div>
          )}
        </section>
      )}
    </main>
  );
}

function PlanReviewCard({
  review,
  decision,
  feedback,
  onDecisionChange,
  onFeedbackChange,
  onSubmit,
}) {
  return (
    <div className="review-box">
      <h3>研究计划待确认</h3>
      <p>
        {review.plan?.title || "未命名研究计划"} · 修订次数{" "}
        {review.revision_count}/{review.max_plan_revisions}
      </p>
      <ul>
        {review.plan?.sections?.map((section) => (
          <li key={section}>{section}</li>
        ))}
      </ul>
      <div className="checkbox-row">
        <label>
          <input
            type="radio"
            name="plan-decision"
            checked={decision === "accept"}
            onChange={() => onDecisionChange("accept")}
          />
          接受计划
        </label>
        <label>
          <input
            type="radio"
            name="plan-decision"
            checked={decision === "revise"}
            onChange={() => onDecisionChange("revise")}
          />
          要求修改
        </label>
      </div>
      {decision === "revise" && (
        <textarea
          value={feedback}
          onChange={(event) => onFeedbackChange(event.target.value)}
          placeholder="请描述需要如何调整研究计划"
          rows={3}
        />
      )}
      <button className="primary-button" onClick={onSubmit}>
        提交审核结果
      </button>
    </div>
  );
}

function ReportView({ result, artifacts }) {
  const payload = result.result || {};
  const sections = payload.section_research || [];
  const warnings = result.warnings || [];

  return (
    <div className="report-view">
      <div className="report-toolbar">
        <h3>研究报告</h3>
        {artifacts.length > 0 && (
          <div className="artifact-links">
            {artifacts.map((artifact) => (
              <a key={artifact.id} href={artifact.download_url}>
                下载 {artifact.format}
              </a>
            ))}
          </div>
        )}
      </div>

      {warnings.length > 0 && (
        <div className="warning-box">
          <strong>警告</strong>
          {warnings.map((warning, index) => (
            <p key={`${warning.code}-${index}`}>
              {warning.code}: {warning.message}
            </p>
          ))}
        </div>
      )}

      <div className="report-section">
        <h4>研究计划</h4>
        <p>{payload.plan?.title}</p>
        <ul>
          {payload.plan?.sections?.map((section) => (
            <li key={section}>{section}</li>
          ))}
        </ul>
      </div>

      <div className="report-section">
        <h4>章节研究</h4>
        {sections.map((item) => (
          <details key={item.section}>
            <summary>{item.section}</summary>
            <pre>{item.content || "该章节研究失败或内容为空。"}</pre>
          </details>
        ))}
      </div>

      <div className="report-section">
        <h4>完整报告</h4>
        <pre className="markdown-output">
          {payload.report_markdown || "报告内容为空。"}
        </pre>
      </div>

      {payload.sources?.length > 0 && (
        <div className="report-section">
          <h4>来源</h4>
          <ul>
            {payload.sources.map((source) => (
              <li key={source}>{source}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
