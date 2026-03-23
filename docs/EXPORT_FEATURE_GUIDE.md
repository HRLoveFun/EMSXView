# LocalStorage缓存导出功能指南

## 功能概述

实现了从浏览器LocalStorage扫描并导出真实Bloomberg API数据的功能。

## 实现代码

### 核心导出函数

**文件**: `app/src/services/strategy-data-service.ts`

```typescript
export function exportConfiguration(): void {
  const brokers = {};
  const params = {};

  // 扫描LocalStorage中的所有键
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    
    // 匹配策略列表缓存: emsx_cache_broker_strategies_{broker}
    const strategiesMatch = key.match(/^emsx_cache_broker_strategies_(.+)$/);
    if (strategiesMatch) {
      const broker = strategiesMatch[1];
      const data = JSON.parse(localStorage.getItem(key));
      brokers[broker] = {
        assetClasses: [data.data.assetClass],
        strategies: data.data.strategies,
      };
    }

    // 匹配策略参数缓存: emsx_cache_strategy_info_{broker}_{strategy}
    const infoMatch = key.match(/^emsx_cache_strategy_info_(.+)_(.+)$/);
    if (infoMatch) {
      const broker = infoMatch[1];
      const strategy = infoMatch[2];
      const data = JSON.parse(localStorage.getItem(key));
      params[broker][strategy] = {
        fields: data.data.fields,
      };
    }
  }

  // 导出为JSON文件下载
  const exportData = { brokers, strategies: params };
  downloadJson(exportData, `emsx-strategy-export-${date}.json`);
}
```

## 使用方式

### 方式一：UI按钮（推荐）

1. 点击Toolbar中的 **Strategy Data** 按钮
2. 在弹出的对话框中点击 **Export Config**
3. 浏览器自动下载JSON文件

### 方式二：浏览器控制台

1. 按 **F12** 打开DevTools
2. 切换到 **Console** 标签
3. 运行导出脚本（见 `scripts/export-localstorage-cache.js`）

## 导出数据格式

```json
{
  "version": "1.0",
  "exportedAt": "2025-03-17T10:30:00.000Z",
  "description": "Exported from LocalStorage cache - REAL Bloomberg API data",
  "source": "Bloomberg API via LocalStorage cache",
  "brokers": {
    "BMTB": {
      "assetClasses": ["EQTY"],
      "strategies": ["", "DMA", "TWAP", "VWAP"]
    }
  },
  "strategies": {
    "BMTB": {
      "TWAP": {
        "fields": [
          {
            "fieldName": "StartTime",
            "stringValue": "09:30:00",
            "disable": "0"
          }
        ]
      }
    }
  }
}
```

## 导出流程

```
┌─────────────────────────────────────────────────────────────┐
│  1. 用户使用策略功能（如修改Route策略）                        │
│     → 调用Bloomberg API                                      │
│     → 数据缓存到LocalStorage                                  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  2. 点击"Export Config"按钮                                  │
│     → 扫描LocalStorage所有键                                  │
│     → 匹配 emsx_cache_* 格式的缓存键                          │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  3. 解析缓存数据                                              │
│     → 提取brokers和strategies                                │
│     → 构建导出JSON对象                                        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  4. 下载JSON文件                                              │
│     → 生成下载链接                                            │
│     → 触发浏览器下载                                          │
└─────────────────────────────────────────────────────────────┘
```

## LocalStorage缓存键格式

系统缓存API数据时使用的键格式：

| 数据类型 | LocalStorage键格式 | 示例 |
|---------|-------------------|------|
| 策略列表 | `emsx_cache_broker_strategies_{broker}` | `emsx_cache_broker_strategies_BMTB` |
| 策略参数 | `emsx_cache_strategy_info_{broker}_{strategy}` | `emsx_cache_strategy_info_BMTB_TWAP` |

## 控制台日志输出

导出时会输出详细日志：

```
[StrategyDataService] Starting LocalStorage scan for cached API data...
[StrategyDataService] Scanning 15 LocalStorage entries...
[StrategyDataService] Found strategies cache for broker: BMTB {...}
[StrategyDataService] Found strategy info cache: BMTB/TWAP {...}
[StrategyDataService] Scan complete: 1 brokers, 3 strategy params found
```

## 填充配置文件的步骤

### 1. 导出数据
点击 **Export Config** 下载JSON文件

### 2. 复制到配置文件

**default-strategies.json**:
```json
{
  "version": "1.0",
  "lastUpdated": "2025-03-17T10:30:00Z",
  "brokers": {
    // 从导出文件的 "brokers" 部分复制到这里
  }
}
```

**default-strategy-params.json**:
```json
{
  "version": "1.0",
  "lastUpdated": "2025-03-17T10:30:00Z",
  "strategies": {
    // 从导出文件的 "strategies" 部分复制到这里
  }
}
```

### 3. 重新加载
点击 **Strategy Data** → **Reload Files**

## 注意事项

1. **必须先使用策略功能**：导出前必须先在UI中使用过策略功能，这样数据才会被缓存到LocalStorage
2. **数据真实性**：导出的数据来自真实的Bloomberg API响应
3. **定期更新**：当Broker策略更新时，需要重新导出
4. **浏览器限制**：导出功能必须在浏览器环境中运行，依赖LocalStorage API

## 故障排查

### 问题：导出时显示"No cached data found"

**原因**：LocalStorage中没有缓存数据

**解决**：
1. 确保已连接Bloomberg
2. 使用策略功能（如修改Route策略）
3. 查看DevTools → Application → Local Storage，确认有`emsx_cache_*`键
4. 重新导出

### 问题：导出的数据不完整

**原因**：只使用了部分Broker/Strategy，其他数据未被缓存

**解决**：
1. 在UI中使用更多的Broker和Strategy组合
2. 每个组合都会被独立缓存
3. 再次导出即可获取完整数据
