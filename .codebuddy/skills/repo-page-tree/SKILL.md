---
name: repo-page-tree
description: 远端仓库目录网页链接生成 skill —— 当用户说「输出远端仓库目录」「生成远端仓库目录结构」「列出远端仓库各目录的网址」「输出仓库每个页面的网址」「输出远端仓库目录」时，运行脚本生成仓库所有目录（tree 页面）在 GitHub/GitLab 上的网页地址，并直接打印到对话框内展示。支持通过参数同时输出文件（blob）页面、指定分支/标签、或写入文件。
---

# 远端仓库目录网页链接生成（Repo Page Tree）

把本地 git 仓库的目录结构映射成远端托管平台（GitHub / GitLab）的网页 URL，
直接在对话框内输出，方便用户点击跳转。

典型输出形如：

```
https://github.com/HRLoveFun/EMSXView/tree/main
https://github.com/HRLoveFun/EMSXView/tree/main/CostView
https://github.com/HRLoveFun/EMSXView/tree/main/CostView/src/monitoring
```

## 触发条件

满足以下任一表述即触发本 skill：

- 「输出远端仓库目录」/「输出远端仓库目录即可在对话框内生成目录」
- 「生成远端仓库目录结构」
- 「列出远端仓库各目录的网址 / 网页链接」
- 「输出仓库每个页面的网址」

## 工作方式

本 skill 不重写代码，而是调用已就绪的脚本 `scripts/repo_page_tree.py` 完成生成。

### 步骤 1：确认意图

- 默认只需**目录（tree）页面**。
- 若用户想要文件链接，加 `--with-files`。
- 若用户指定了分支/标签，加 `--branch <分支名>`。

### 步骤 2：运行脚本并在对话框内展示

默认（仅目录页面）直接在对话框打印结果：

```bash
python scripts/repo_page_tree.py
```

带文件的完整页面：

```bash
python scripts/repo_page_tree.py --with-files
```

指定分支：

```bash
python scripts/repo_page_tree.py --branch main
```

### 步骤 3：把输出呈现给用户

脚本会把所有 URL 打印到标准输出，**直接将这整段输出复制到对话框回复给用户**即可，
无需再解释——用户要的就是这份目录清单本身。结尾脚本会附上「# 共 N 条」便于核对。

## 实现要点（脚本内部逻辑，便于排障）

1. **远端地址归一化**：`git@github.com:owner/repo.git`（SSH）与
   `https://host/owner/repo.git`（HTTPS）统一成 `https://host/owner/repo`。
2. **目录靠文件反推**：`git ls-files` 只列被跟踪文件，不列目录；
   脚本用每个文件的父目录链推导出所有 `tree` 页面，因此**空目录不会出现在结果里**。
3. **路径编码**：目录/文件名含空格、`#` 等字符时用 `urllib.parse.quote` 编码，避免链接失效。
4. **平台兼容**：GitHub 与 GitLab 的链接规则一致（`/tree/分支/路径`、`/blob/分支/路径`），
   仅 base 域名不同，无需区分。
5. **错误处理**：无 `origin` 或不在 git 仓库内时，脚本会给出中文报错并退出，
   此时把报错原样告知用户，并提示先 `git remote add origin` 或在仓库根目录运行。

## 常见变体

| 用户想要 | 命令 |
|---|---|
| 仅目录页面（默认） | `python scripts/repo_page_tree.py` |
| 目录 + 文件页面 | `python scripts/repo_page_tree.py --with-files` |
| 指定分支/标签 | `python scripts/repo_page_tree.py --branch <分支>` |
| 仅指定子目录子树 | `python scripts/repo_page_tree.py --subdir CostView` |
| 仅保留 2026 年起更新的文件 | `python scripts/repo_page_tree.py --since 2026-01-01` |
| 近 3 个月更新的文件+页面 | `python scripts/repo_page_tree.py --since "3 months ago" --with-files` |
| 某日期前更新的（含子目录） | `python scripts/repo_page_tree.py --until 2026-06-01 --subdir CostView` |
| 写入文件 | `python scripts/repo_page_tree.py --output pages.txt` |
