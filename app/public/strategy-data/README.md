# Strategy Data Files

此目录存储Broker Strategies和Strategy Parameters的缓存数据文件。

## ⚠️ 重要声明

**所有数据必须来自Bloomberg API，不能手动编造！**

这些文件仅用于：
- 快速加载（减少API等待时间）
- 离线查看（只读，不能修改）
- API故障时的后备显示

**离线时不能执行任何修改操作，必须先恢复Bloomberg连接。**

## 文件说明

### `default-strategies.json` (初始为空)
存储各Broker的策略列表。数据必须从API导出后填入。

### `default-strategy-params.json` (初始为空)
存储各Broker-Strategy组合的参数定义。数据必须从API导出后填入。

### `EXPORT_EXAMPLE.json`
展示导出数据的格式示例（仅参考，不是真实数据）。

## 数据获取完整流程

### 第一步：连接Bloomberg并生成缓存

1. 启动前端应用并连接Bloomberg
2. 进入 **Route** 标签页
3. 点击任意Route的 **Modify** 按钮
4. 在弹出的对话框中选择 **Broker & Strategy**
5. 选择一个Broker（如 BMTB）
6. 等待策略列表加载（数据自动缓存到LocalStorage）
7. 选择一个Strategy（如 TWAP）
8. 等待参数加载（数据自动缓存到LocalStorage）

### 第二步：导出缓存数据

**方法A：使用UI按钮（推荐）**
1. 点击Toolbar中的 **Strategy Data** 按钮
2. 在弹出的对话框中点击 **Export Config**
3. 浏览器会下载一个JSON文件

**方法B：使用浏览器控制台**
1. 按 **F12** 打开DevTools
2. 切换到 **Console** 标签
3. 粘贴并运行 `exportLocalStorageCache()` 函数
4. 查看输出的JSON数据

### 第三步：填充配置文件

1. 打开下载的JSON文件（或控制台输出的数据）
2. 找到 `brokers` 部分，复制到 `default-strategies.json`：

```json
{
  "version": "1.0",
  "lastUpdated": "2025-03-17T10:30:00Z",
  "brokers": {
    "BMTB": {
      "assetClasses": ["EQTY"],
      "strategies": ["", "DMA", "TWAP", "VWAP"]
    }
  }
}
```

3. 找到 `strategies` 部分，复制到 `default-strategy-params.json`：

```json
{
  "version": "1.0",
  "lastUpdated": "2025-03-17T10:30:00Z",
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

### 第四步：重新加载文件缓存

1. 点击Toolbar中的 **Strategy Data** 按钮
2. 点击 **Reload Files**
3. 现在文件缓存已包含真实API数据

## LocalStorage缓存键格式

系统会自动将API数据缓存到LocalStorage，键格式如下：

```
emsx_cache_broker_strategies_{broker}     # 存储策略列表
emsx_cache_strategy_info_{broker}_{strategy}  # 存储策略参数
```

示例：
```
emsx_cache_broker_strategies_BMTB
emsx_cache_strategy_info_BMTB_TWAP
```

## 设置默认参数值

在`default-strategy-params.json`中，**只能修改`stringValue`字段**：

```json
{
  "BMTB": {
    "TWAP": {
      "fields": [
        {
          "fieldName": "StartTime",
          "stringValue": "10:00:00",  // ← 可以修改，设置你的默认值
          "disable": "0"              // ← 不要修改，来自API
        }
      ]
    }
  }
}
```

## 离线限制

**离线或API故障时：**
- ✅ 可以查看策略列表
- ✅ 可以查看参数结构
- ❌ **不能修改策略参数**
- ❌ **不能执行交易操作**

**必须先恢复Bloomberg连接才能进行任何修改。**

## 故障排除

### 导出时显示"No cached data found"

**原因**：LocalStorage中没有缓存的API数据

**解决方法**：
1. 确保已连接Bloomberg
2. 使用策略功能（如修改Route策略）
3. 数据会自动缓存到LocalStorage
4. 然后再执行导出

### 如何查看LocalStorage中的缓存？

1. 按 **F12** 打开DevTools
2. 切换到 **Application** 标签（Chrome）或 **Storage** 标签（Firefox）
3. 在左侧选择 **Local Storage** → **http://localhost:5173**
4. 查看以 `emsx_cache_` 开头的键

### 如何清除缓存？

**方法A：使用UI**
1. 点击 **Strategy Data** → **Clear All Caches**

**方法B：使用浏览器**
1. 打开DevTools → Application → Local Storage
2. 右键点击 → Clear

## 注意事项

1. **数据来源**：所有数据必须通过Bloomberg API获取
2. **定期更新**：当Broker更新策略时，需要重新导出
3. **版本控制**：可以将这些文件提交到git，便于团队共享
4. **敏感信息**：不要在这些文件中存储敏感信息
5. **文件编码**：确保使用UTF-8编码保存JSON文件
