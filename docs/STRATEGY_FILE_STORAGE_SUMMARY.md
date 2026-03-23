# Strategy File Storage 功能实现总结

## 重要声明

**所有数据必须来自Bloomberg API，不能手动编造！**

本地文件存储仅用于：
1. **快速加载** - 减少API等待时间
2. **离线查看** - 连接断开时仍可查看（只读）
3. **API故障回退** - 超时时显示文件数据（只读）

**离线时不能执行任何修改操作，必须先恢复Bloomberg连接。**

## 实现概述

为低频更新的 Broker Strategies 和 Strategy Parameters 建立了**文件存储系统**。

## 文件结构

### 配置文件（初始为空，需从API导出）

| 文件路径 | 说明 |
|---------|------|
| `app/public/strategy-data/default-strategies.json` | 存储各Broker的algorithm列表 |
| `app/public/strategy-data/default-strategy-params.json` | 存储algorithm parameter定义和默认值 |
| `app/public/strategy-data/README.md` | 使用说明 |

### 服务代码

| 文件路径 | 说明 |
|---------|------|
| `app/src/services/strategy-data-service.ts` | 文件数据读取、合并、导出服务 |
| `app/src/components/strategy-data-manager.tsx` | 管理工具UI组件 |

### 文档

| 文件路径 | 说明 |
|---------|------|
| `docs/strategy-file-storage.md` | 详细架构说明 |

## 数据获取流程

```
1. 连接Bloomberg API
   ↓
2. 在应用中使用algorithm功能（修改Routealgorithm等）
   ↓
3. 数据自动缓存到LocalStorage
   ↓
4. 点击Toolbar中的"Strategy Data"按钮
   ↓
5. 点击"Export Config"导出真实API数据
   ↓
6. 将导出的数据复制到JSON配置文件中
   ↓
7. 后续离线时可使用这些缓存数据查看
```

## 使用方法

### 获取真实数据

1. **连接Bloomberg**，确保API正常
2. **使用algorithm功能**（如修改Route的algorithm），数据会缓存到LocalStorage
3. 点击Toolbar中的 **Strategy Data** 按钮
4. 点击 **Export Config**，下载包含真实数据的JSON文件
5. 将文件内容复制到 `default-strategies.json` 和 `default-strategy-params.json`
6. 点击 **Reload Files** 重新加载

### 设置默认parameter值（仅可修改stringValue）

在`default-strategy-params.json`中：
```json
{
  "BMTB": {
    "TWAP": {
      "fields": [
        {
          "fieldName": "StartTime",
          "stringValue": "10:00:00",  // 可以修改，设置你的默认值
          "disable": "0"              // 不要修改，来自API
        }
      ]
    }
  }
}
```

## 三层缓存架构

```
┌─────────────────────────────────────────────────────────────┐
│  L1: 内存缓存 (Map) - 会话级，最快访问                        │
│  L2: LocalStorage - 24小时TTL，跨会话持久化                   │
│  L3: JSON文件 - 必须从API导出，离线/快速加载                   │
└─────────────────────────────────────────────────────────────┘
```

## 离线限制

**离线或API故障时：**
- ✅ 可以查看algorithm列表
- ✅ 可以查看parameter结构
- ❌ **不能修改algorithm parameter**
- ❌ **不能执行交易操作**

**必须先恢复Bloomberg连接才能进行任何修改。**

## 核心功能

### 1. 故障回退机制
API失败时自动回退到文件数据，但标记为只读：
```typescript
return { 
  success: true, 
  data: fileData, 
  message: 'From file (API unavailable) - READ ONLY' 
};
```

### 2. 默认值合并
API数据与文件默认值合并时，文件的`stringValue`作为默认值：
```typescript
// API返回: "09:30:00"
// 文件配置: "10:00:00"
// 最终显示: "10:00:00"（文件默认值）
```

## 管理工具功能

点击Toolbar中的 **Strategy Data** 按钮：
- **Cache Status**: 查看文件缓存和API缓存状态
- **Reload Files**: 重新加载JSON文件
- **Clear All Caches**: 清除所有缓存
- **Export Config**: 从LocalStorage导出真实API数据
- **Import**: 导入配置（开发中）

## 注意事项

1. **数据来源**: 所有数据必须通过Bloomberg API获取，不能编造
2. **定期更新**: 当Broker更新algorithm时，需要重新导出更新
3. **版本控制**: 可以将这些文件提交到git，便于团队共享
4. **离线限制**: 离线时只能查看，不能修改任何数据
5. **修改操作**: 所有修改都需要连接Bloomberg
