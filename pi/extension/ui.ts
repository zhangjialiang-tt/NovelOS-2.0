/**
 * 状态板渲染与错误转译。
 *
 * 冻结文档 05 §2.2：状态板四要素（阶段/已完成/当前问题/建议动作）。
 * 冻结文档 05 §6.1/§6.2：退出码 5 与特定错误码的用户转译。
 * 冻结文档 05 §7：不展示内部路径、hash、JSON 字段名、错误码枚举名。
 *
 * 纯函数、无 pi 依赖 → 可单测（pi/extension/test/ui.test.ts）。
 */

export interface StatusData {
  initialized: boolean;
  project: string | null;
  stage: string | null;
  completed: string[];
  issues: string[];
  legal_actions: string[];
}

export interface NextData {
  suggested_action: string | null;
  task_type: string | null;
  subject: string | null;
  reason: string;
  /** 机器可读码（NOT_INITIALIZED / NO_ACTION_IMPLEMENTED），Core 增补字段。 */
  reason_code?: string | null;
  /** 可原样呈现给作者的文案，Core 增补字段。 */
  user_message?: string | null;
}

const STAGE_HUMAN: Record<string, string> = {
  initialized: "已初始化",
  premise_in_progress: "故事核心创作中",
  premise_accepted: "故事核心已确定",
};

export function humanStage(stage: string | null): string {
  if (stage === null) return "未知";
  return STAGE_HUMAN[stage] ?? stage;
}

export function renderNotInitialized(): string {
  return "作品尚未初始化。告诉我一个故事想法，或用 /novelos 引导创建。";
}

/** next 为 null 时渲染纯状态板（/novelos-status，冻结文档 05 §2.1：无建议动作栏）。 */
export function renderStatusBoard(status: StatusData, next: NextData | null): string {
  const lines: string[] = [];
  lines.push(`作品：《${status.project ?? "未命名"}》`);
  lines.push(`当前阶段：${humanStage(status.stage)}`);
  if (status.completed.length === 0) {
    lines.push("已完成：（无）");
  } else {
    lines.push("已完成：");
    for (const item of status.completed) lines.push(`  ✓ ${item}`);
  }
  if (status.issues.length === 0) {
    lines.push("当前问题：无阻塞");
  } else {
    lines.push("当前问题：");
    for (const issue of status.issues) lines.push(`  ${issue}`);
  }
  if (next !== null) {
    lines.push(`建议动作：${next.user_message ?? next.reason}`);
  }
  return lines.join("\n");
}

/** 退出码 5 环境错误转译（冻结文档 05 §6.1）。 */
export function translateEnvError(code: "CORE_LAUNCHER_NOT_FOUND" | "CORE_VERSION_MISMATCH"): string {
  if (code === "CORE_LAUNCHER_NOT_FOUND") return "核心组件未找到。运行安装脚本。";
  return "版本不兼容。更新安装。";
}

/** 信封错误转译为用户动作（冻结文档 05 §6.1/§6.2/§7：不暴露错误码）。 */
export function translateEnvelopeError(errors: Array<{ code: string; message: string }>): string {
  const first = errors[0];
  if (!first) return "系统异常，请重试或运行 novelos doctor。";
  switch (first.code) {
    case "WORKSPACE_CORRUPT":
      return "作品数据异常。运行 novelos doctor 诊断；不可恢复时从 checkpoint 恢复。";
    case "NOT_INITIALIZED":
      return "还没有作品。要开始新故事吗？";
    case "OUT_OF_BAND_WRITE_DETECTED":
      return "检测到系统外修改。请从最近 checkpoint 恢复后重跑。";
    default:
      return "系统异常，请重试或运行 novelos doctor。";
  }
}

/** 信封错误 → 文本（message（hint）拼接；工具结果通道，不做用户转译）。 */
export function envelopeErrorsText(
  errors: Array<{ code: string; message: string; hint?: string }>,
): string {
  return errors
    .map((e) => `${e.message}${e.hint ? `（${e.hint}）` : ""}`)
    .join("\n");
}

/** present 返回的预览项（04 §3.5/r5）。 */
export interface PreviewContentItem {
  artifact_id: string;
  base_artifact_ref: string | null;
  preview_kind: string;
  content: string;
}

/** present_packet 的呈现所需子集（05 §3.1/§7：人类可读，不展示 hash/字段名/内部路径）。 */
export interface PresentPacket {
  changed_files: string[];
  diff_statistics: { added: number; removed: number; files: number };
  previous_artifact_revisions: unknown[];
}

const FILE_HUMAN: Record<string, string> = {
  "story/premise.md": "故事核心",
};

/** decide 对话框标题：preview 全文 + 变更摘要（previous_artifact_revisions 空则隐藏）。 */
export function renderDecidePreview(
  previewContent: PreviewContentItem[],
  packet: PresentPacket | null,
): string {
  const lines: string[] = ["候选已就绪，请审阅全文并决定：", ""];
  for (const item of previewContent) {
    if (typeof item.content === "string" && item.content !== "") {
      lines.push(item.content, "");
    }
  }
  if (packet !== null) {
    if (packet.changed_files.length > 0) {
      const names = packet.changed_files.map((f) => FILE_HUMAN[f] ?? "作品文件");
      lines.push(`变更内容：${names.join("、")}`);
    }
    const s = packet.diff_statistics;
    lines.push(`新增 ${s.added} 行 / 删除 ${s.removed} 行 / ${s.files} 个文件`);
    if (packet.previous_artifact_revisions.length > 0) {
      lines.push(`影响既有正式版本：${packet.previous_artifact_revisions.length} 项`);
    }
  }
  return lines.join("\n");
}
