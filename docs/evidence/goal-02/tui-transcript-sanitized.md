# 真实 Pi TUI 演示脱敏转录（Goal 2 完成判据，2026-07-30）

环境：pi v0.82.1 · LongCat-2.0（thinking off）· cwd = `<demo-dir>`（空目录）·
Extension/Skill 经 junction 指向仓库分支 `goal/02b-premise-pi`。
脱敏规则：创作正文以占位符代替；绝对路径以 `<demo-dir>`/`<user-home>` 代替；无认证信息。

## 第一段：init → rev-1 → REVISE

    用户> /novelos
    通知> 作品尚未初始化。告诉我一个故事想法，或用 /novelos 引导创建。

    用户> 我想写一个记忆当铺的故事：〈故事设定一句话〉
    Agent> 初始化成功。现在我需要再次检查状态，然后可以开始 premise 创作任务。
      tool novelos_status → {"initialized": true, "project": "记忆当铺", "stage": "initialized",
                             "completed": [], "issues": [], "legal_actions": ["premise"]}
      tool novelos_init   → 已初始化：<demo-dir>
    Agent> 现在项目已初始化，合法动作包含 premise。根据 skill 的指引，我需要：
           1. 先收集用户的想法（brief） 2. 然后调用 novelos_open_task 创建 premise 任务
           用户已经给出了故事想法：〈设定要点三条〉
      tool novelos_open_task {task_type: premise, brief: …}
           → 已创建任务 task-001；staging: work/task-001，请先阅读 .novelos/tasks/task-001/instructions.md
      tool read <demo-dir>\.novelos\tasks\task-001\instructions.md
    Agent> 我已经读取了任务工作包说明。现在我需要根据用户的故事想法，创作一个 premise.md 文件，
           包含八个小节：一句话故事钩子 / 主角是谁 / 主角主动目标 / 核心阻力 / 失败代价 /
           主要读者期待 / 结局方向 / 尚待作者决定的问题。
      tool write <demo-dir>\work/task-001/premise.md   # 八节正文（略）
    Agent> 文件已写入。现在需要提交候选并校验。
      tool novelos_submit_candidate → 候选已提交（rev-1）。请调用 novelos_validate 校验。
      tool novelos_validate         → 校验通过。请调用 novelos_present 向作者呈现候选。
      tool novelos_present          → 已向作者呈现候选。请调用 novelos_decide 由作者决定。
      tool novelos_decide
    ┌─ TUI 对话框 ────────────────────────────────────────────────
    │ 候选已就绪，请审阅全文并决定：
    │ ## 一句话故事钩子 〈正文略〉 … ## 尚待作者决定的问题 〈正文略〉
    │ 变更内容：故事核心
    │ 新增 41 行 / 删除 0 行 / 1 个文件
    │ → ACCEPT（保存为正式版本）
    │   REVISE（补充意见后重写）
    │   REJECT（丢弃草稿）
    │ ↑↓ navigate  enter select  escape/ctrl+c cancel
    └────────────────────────────────────────────────────────────
    操作> ↓ ENTER（选 REVISE）
    ┌─ TUI 输入 ─────────────────────────────────────────────────
    │ 作者修改意见（将进入下一轮创作任务）
    │ > 把失败代价写得更具体
    └────────────────────────────────────────────────────────────
      tool novelos_decide → 已记录修改意见：「把失败代价写得更具体」。
                            请重读 .novelos/tasks/task-001/instructions.md 与
                            .novelos/tasks/task-001/context/revision-notes/rev-001.md 后生成新候选。

## 第二段：重读意见 → rev-2 → ACCEPT → checkpoint

    Agent> 作者要求修改，需要读取 revision note 来了解具体意见。
      tool read <demo-dir>\.novelos\tasks\task-001\context\revision-notes\rev-001.md
    Agent> 作者要求把失败代价写得更具体。我需要修改 premise.md 中的"失败代价"部分，
           让它更加具体、有画面感、有细节。
      tool edit <demo-dir>\work/task-001\premise.md
           - ## 失败代价 〈原泛化段落〉
           + ## 失败代价 〈具体化：对世界/对主角/对师父三重代价，略〉
    Agent> 修改完成，现在重新提交并校验。
      tool novelos_submit_candidate → 候选已提交（rev-2）。
      tool novelos_validate         → 校验通过。
      tool novelos_present          → 已向作者呈现候选。
      tool novelos_decide
    ┌─ TUI 对话框（同构；新增 45 行 / 1 个文件；preview 含具体化失败代价，略）─┐
    操作> ENTER（选 ACCEPT）
    Agent> 〈以作者语言报喜：故事核心已确定，呈报设定摘要表与 5 个待作者决定问题〉

    用户> 保存进度
      tool novelos_checkpoint → 已保存检查点：cp-001。
    Agent> 进度已保存 ✅ 检查点 cp-001 已记录。

    操作> CTRL_C ×2 / CTRL_D → pi 退出（exit 0）

## 第三段：重启恢复

    （重开 pi，同目录）
    用户> /novelos
    通知> 作品：《记忆当铺》
          当前阶段：故事核心已确定
          已完成：
            ✓ 故事核心方向
          当前问题：无阻塞
          建议动作：故事核心已确定。当前版本尚未开放故事规划。

## 带外核验

    $ python -m novelos integrity-scan --json --workspace <demo-dir>
    {"ok": true, "data": {"scanned_files": 2, "blocking_mismatches": [], "derived_dirty": [],
     "chain_ok": true, "anchor_ok": true, "chain_detail": ""}, "errors": []}   # exit 0

    # story/premise.md 含 rev-2 具体化内容（「溯源术」「空壳状态」各出现）
    # .novelos/decisions.jsonl 两行：REVISE/ACCEPT 皆 INTERACTIVE_UI、consumed=true
    # events.jsonl 无 FALLBACK/SEEDED；find <demo-dir> -name SKILL.md → 0
