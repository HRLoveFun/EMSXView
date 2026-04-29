import { useState } from 'react';
import { Info, ChevronDown, ChevronRight } from 'lucide-react';

/**
 * Discoverable, dismissible callout that tells the user how to restart
 * services after a code change. Targeted at non-technical users who do not
 * know what "FastAPI" or "npm run dev" means.
 *
 * Only shown when the page is loaded from localhost (i.e. the developer /
 * researcher running the local stack). Hidden in remote/production loads
 * where the user has no shell access anyway.
 */
export function RestartHint() {
  const [open, setOpen] = useState(false);

  const isLocal =
    typeof window !== 'undefined' &&
    /^(localhost|127\.0\.0\.1|::1)$/.test(window.location.hostname);
  if (!isLocal) return null;

  return (
    <div className="rounded-xl border border-sky-200 bg-sky-50/60 p-3 text-xs text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-left"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" />
        )}
        <Info className="h-3.5 w-3.5" />
        <span className="font-medium">看到的字段或功能与最新代码不一致？点这里看怎么办</span>
      </button>

      {open && (
        <div className="mt-2 space-y-2 pl-6 leading-relaxed">
          <p>
            后端 (FastAPI) 修改 Python 代码后需要重启才能生效；前端代码通常会自动热更新，但少数改动也需要重启。
          </p>
          <p className="font-medium text-sky-900 dark:text-sky-100">
            最简单的做法：双击项目根目录里的{' '}
            <code className="rounded bg-sky-100 px-1.5 py-0.5 font-mono dark:bg-sky-900/60">
              重启服务.bat
            </code>
          </p>
          <ol className="list-decimal space-y-0.5 pl-5 text-[11px]">
            <li>
              打开文件夹{' '}
              <code className="font-mono">C:\Users\hrchen\Documents\EMSX</code>
            </li>
            <li>
              找到{' '}
              <code className="rounded bg-sky-100 px-1.5 py-0.5 font-mono dark:bg-sky-900/60">
                重启服务.bat
              </code>{' '}
              这个文件，<strong>双击</strong>它
            </li>
            <li>等黑色窗口出现「[成功] 服务已重启完成」后，浏览器会自动刷新到前端页面</li>
            <li>
              在本页右上角点{' '}
              <code className="rounded bg-sky-100 px-1.5 py-0.5 font-mono dark:bg-sky-900/60">
                Refresh
              </code>{' '}
              即可看到最新数据
            </li>
          </ol>
          <p className="text-[10px] text-sky-700 dark:text-sky-400">
            提示：建议把这个 .bat 文件{' '}
            <strong>右键 ▸ 发送到 ▸ 桌面快捷方式</strong>，以后在桌面上一键重启即可。
          </p>
        </div>
      )}
    </div>
  );
}
