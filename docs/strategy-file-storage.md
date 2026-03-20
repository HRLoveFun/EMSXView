# Strategy File Storage 架构说明

## 概述

本功能为低频更新的Broker Strategies和Strategy Parameters建立了**文件存储系统**，用于：

1. **快速加载** - 首次加载优先使用文件数据，减少API等待时间
2. **离线查看** - Bloomberg连接断开时仍可查看策略信息（只读）
3. **API故障回退** - API超时时自动回退到文件数据（只读）

**重要：所有数据必须来自Bloomberg API，不能手动编造！**

## 数据流

### 正常流程（API可用）
```
用户操作 → 调用Bloomberg API → 成功 → 更新LocalStorage → 返回数据
                              ↓
                         同时更新文件缓存
```

### API故障/离线流程
```
用户操作 → 调用Bloomberg API → 失败 → 回退到文件数据 → 显示"只读"标记
                              ↓
                    提示用户需要恢复连接才能修改
```

## 文件结构

### `public/strategy-data/default-strategies.json`
初始为空，需要从API导出数据填充：
```json
{
  "version": "1.0",
  "lastUpdated": "2025-03-17T00:00:00Z",
  "brokers": {
    "BMTB": {
      "assetClasses": ["EQTY"],
      "strategies": ["", "DMA", "TWAP", "VWAP"]
    }
  }
}
```

### `public/strategy-data/default-strategy-params.json`
初始为空，需要从API导出数据填充：
```json
{
  "version": "1.0",
  "lastUpdated": "2025-03-17T00:00:00Z",
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

## 数据获取流程

### 第一步：连接Bloomberg并填充缓存
1. 启动应用并连接Bloomberg
2. 正常使用策略功能（修改Route的策略等）
3. 数据自动缓存到LocalStorage

### 第二步：导出缓存数据
1. 点击Toolbar中的 **Strategy Data** 按钮
2. 点击 **Export Config**
3. 下载包含真实API数据的JSON文件

### 第三步：填充配置文件
1. 打开导出的JSON文件
2. 将 `brokers` 部分复制到 `default-strategies.json`
3. 将 `strategies` 部分复制到 `default-strategy-params.json`
4. 保存文件

### 第四步：重新加载
1. 点击 **Strategy Data** → **Reload Files**
2. 文件缓存现在包含真实数据

## 使用限制

**离线或API故障时：**
- ✅ 可以查看策略列表
- ✅ 可以查看参数结构
- ❌ **不能修改策略参数**
- ❌ **不能执行交易操作**

**所有修改操作都需要：**
- Bloomberg连接正常
- API响应成功

## 三层缓存架构

| 层级 | 存储位置 | 数据来源 | 用途 |
|------|---------|---------|------|
| L1 | 内存 (Map) | API/LocalStorage | 当前页面快速访问 |
| L2 | LocalStorage | API | 跨会话持久化（24小时） |
| L3 | JSON文件 | **必须从API导出** | 离线/快速加载 |

## 核心功能

### 1. 故障回退机制

当Bloomberg API调用失败时：
```typescript
try {
  const data = await apiService.getBrokerStrategyInfo(...);
} catch (error) {
  // API失败，尝试文件回退
  const fileData = await getStrategyInfoFromFile(broker, strategy);
  if (fileData) {
    return { 
      success: true, 
      data: fileData, 
      message: 'From file (API unavailable) - READ ONLY' 
    };
  }
}
```

### 2. 默认值设置

在`default-strategy-params.json`中，**只能修改`stringValue`字段**：

```json
{
  "BMTB": {
    "TWAP": {
      "fields": [
        {
          "fieldName": "StartTime",
          "stringValue": "10:00:00",  // 可以修改，设置你的默认开始时间
          "disable": "0"              // 不要修改，来自API
        }
      ]
    }
  }
}
```

## 管理工具

点击Toolbar中的 **Strategy Data** 按钮：

### Cache Status
- 查看文件缓存状态（从JSON文件加载）
- 查看API缓存状态（从LocalStorage加载）
- 查看可用的Broker列表

### Actions
- **Reload Files**: 重新加载JSON文件
- **Clear All Caches**: 清除所有缓存
- **Export Config**: 从LocalStorage导出真实API数据
- **Import**: 导入配置（开发中）

### Configuration Files
- 显示配置文件路径
- 显示数据获取说明

## 注意事项

1. **数据来源**: 所有数据必须通过Bloomberg API获取，不能手动编造
2. **定期更新**: 当Broker更新策略时，需要重新导出更新
3. **版本控制**: 可以将这些文件提交到git，便于团队共享
4. **离线限制**: 离线时只能查看，不能修改任何数据
5. **修改操作**: 所有修改策略参数的操作都需要连接Bloomberg

## 常见问题

### Q: 为什么文件初始是空的？
A: 因为数据必须从Bloomberg API获取，不能预设。连接Bloomberg并使用功能后，可以导出数据填充文件。

### Q: 离线时能做什么？
A: 只能查看策略列表和参数结构，不能执行任何修改操作。

### Q: 如何更新文件中的数据？
A: 连接Bloomberg，使用Strategy Data Manager导出当前缓存，然后将数据复制到JSON文件中。

### Q: 可以修改哪些字段？
A: 只能修改`default-strategy-params.json`中的`stringValue`字段来设置默认值。其他字段来自API，不要修改。
