# Session Captures

> 自动捕获的会话信息临时存储目录

## 目录结构

```
session_captures/
├── YYYY-MM-DD/           # 按日期组织的捕获文件
│   ├── summary.md        # 当天摘要（由自动化任务生成）
│   └── *.md             # 单独的关键事件捕获
├── archived/             # 已合并到 HANDOFF.md 的归档文件
│   └── YYYY-MM-DD/
└── README.md            # 本文件
```

## 工作流程

1. **自动捕获**: 每天 18:00 生成 summary.md
2. **用户确认**: 查看并确认捕获内容
3. **合并到 HANDOFF**: 每天 19:00 自动合并（需用户确认）
4. **归档**: 已合并的文件移动到 archived/

## 注意事项

- 此目录下的文件是临时性的，最终应合并到 HANDOFF.md
- archived/ 目录保留历史记录用于追溯
- 定期清理（如保留 3 个月）可手动执行
