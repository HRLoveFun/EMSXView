#!/usr/bin/env node
/**
 * 为根级前端模块链接依赖：确保「仓库根 node_modules」指向 `frontend/node_modules`。
 *
 * 背景：ExecutionView 的源码已独立为仓库根级目录（与 `frontend/` 平级，见
 * `specs/012-executionview-root-extract/plan.md`）。Node / TypeScript / Vite 解析**裸包**
 * 说明符（`react`、`lucide-react` 等）时，是从「引用方文件所在目录逐级向上」查找
 * `node_modules`；仓库根若不存在 `node_modules`，这些裸包在 `ExecutionView/**` 下即解析失败。
 *
 * 方案：在仓库根建立链接指向 `frontend/node_modules`——全仓库只保留**一份物理依赖**
 * （若让 ExecutionView 自带依赖，Vite 可能打包出第二份 React，触发 Invalid hook call）。
 *
 * 触发：`frontend/package.json` 的 `postinstall` 自动调用（`npm install` / `npm ci` 后均生效）。
 * 幂等：已存在且指向正确即返回；指向错误则重建；存在**真实目录**（非链接）时告警跳过，不擅自删。
 *
 * 后续若 costview / marketview 也迁到根级目录，本脚本无需改动（根链接对全部根级目录生效）。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, '..', '..');
const depsRoot = path.join(repoRoot, 'frontend', 'node_modules');
const linkPath = path.join(repoRoot, 'node_modules');
const PREFIX = '[link-module-deps]';

/** 返回路径的真实目标；路径不存在返回 null。 */
function realTarget(pathname) {
  try {
    return fs.realpathSync(pathname);
  } catch {
    return null;
  }
}

function main() {
  if (!fs.existsSync(depsRoot)) {
    console.warn(`${PREFIX} 未找到 frontend/node_modules，跳过（请先在 frontend/ 安装依赖）`);
    return;
  }

  const expected = realTarget(depsRoot);
  if (realTarget(linkPath) === expected) {
    return; // 已就绪
  }

  if (fs.existsSync(linkPath) && !fs.lstatSync(linkPath).isSymbolicLink()) {
    console.warn(`${PREFIX} ${linkPath} 已存在且不是链接，跳过（如需接管请先人工确认删除）`);
    return;
  }

  if (fs.existsSync(linkPath)) {
    fs.rmSync(linkPath, { recursive: false, force: true });
  }
  fs.symlinkSync(depsRoot, linkPath, 'junction');
  console.log(`${PREFIX} 已建立仓库根 node_modules → frontend/node_modules`);
}

try {
  main();
} catch (error) {
  // 依赖安装不应因链接失败而中断：仅告警，由使用方按提示排查
  console.warn(`${PREFIX} 建立根 node_modules 链接失败（${error.message}）`);
}
