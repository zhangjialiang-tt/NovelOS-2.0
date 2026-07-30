# 标准交互循环（冻结文档 01 §6 摘录）

每个创作任务遵循同一循环：

```text
1.  status — 查询当前状态与合法动作
2.  选择合法动作，创建 Task（Core 编译任务工作包）
3.  Agent 读取工作包与必要作品文件，将 Candidate 写入 staging 区
4.  submit_candidate — Core 接管 staging：hash、冻结副本、分配 candidate revision
5.  validate — Core 对冻结 revision 做纯检查
6.  校验失败：Agent 修改 staging，重新 submit（新 candidate revision）+ validate
7.  校验通过：present — Core 计算确定性变更摘要/差异/影响范围，Extension 向作者渲染
8.  作者 ACCEPT / REVISE / REJECT — 决定值来自 Extension 的 UI 回调，不是 Agent 参数
9.  ACCEPT → Core 记录 Decision 并原子 commit；REVISE → Task 保持活跃；REJECT → 终止 Task
10. checkpoint
11. next — 回到 1
```

> 注：status / next / init 与 premise 任务的步骤 2–10 完整循环（open_task/submit/validate/present/decide/checkpoint）已实现；story_plan 起（新任务类型）随后续 Goal 落地。
