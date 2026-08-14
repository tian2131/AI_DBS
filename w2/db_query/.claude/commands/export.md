# 数据库智能导出命令

## 概述
提供命令行方式执行智能导出操作，集成到开发和测试流程中。

## 命令列表

### `export-csv`
将查询结果导出为CSV格式。

**用法:**
```bash
export-csv <database_name> "<sql_query>"
```

**示例:**
```bash
export-csv mydb "SELECT * FROM users LIMIT 1000"
```

**参数:**
- `database_name`: 数据库连接名称
- `sql_query`: 要执行的SQL查询语句

**选项:**
- `--output <filename>`: 指定输出文件名
- `--no-header`: 不包含CSV头部
- `--delimiter <char>`: 指定分隔符（默认为逗号）

### `export-json`
将查询结果导出为JSON格式。

**用法:**
```bash
export-json <database_name> "<sql_query>"
```

**示例:**
```bash
export-json mydb "SELECT * FROM products WHERE price > 100"
```

**参数:**
- `database_name`: 数据库连接名称
- `sql_query`: 要执行的SQL查询语句

**选项:**
- `--output <filename>`: 指定输出文件名
- `--indent <spaces>`: JSON缩进空格数（默认为2）
- `--minify`: 压缩JSON输出

### `auto-export`
智能自动导出，AI选择最佳格式。

**用法:**
```bash
auto-export <database_name> "<sql_query>"
```

**示例:**
```bash
auto-export mydb "SELECT u.*, o.* FROM users u JOIN orders o ON u.id = o.user_id"
```

**参数:**
- `database_name`: 数据库连接名称
- `sql_query`: 要执行的SQL查询语句

**选项:**
- `--force`: 强制导出，跳过确认
- `--show-analysis`: 显示AI分析结果
- `--format <csv|json>`: 指定格式（覆盖AI建议）

### `export-history`
查看导出历史记录。

**用法:**
```bash
export-history
```

**选项:**
- `--limit <number>`: 显示最近N条记录（默认10）
- `--database <name>`: 过滤特定数据库
- `--format <csv|json>`: 过滤特定格式

### `export-stats`
显示导出统计信息。

**用法:**
```bash
export-stats
```

**输出:**
- 总导出次数
- 各格式导出次数
- 平均导出时间
- 总导出行数

## 集成到Makefile

```makefile
# 导出命令
export-csv:
	@echo "Exporting as CSV..."
	cd backend && uv run python -c "from app.workflows.export_workflow import export_workflow; import asyncio; asyncio.run(export_workflow.export_csv('$(DB)', '$(SQL)'))"

export-json:
	@echo "Exporting as JSON..."
	cd backend && uv run python -c "from app.workflows.export_workflow import export_workflow; import asyncio; asyncio.run(export_workflow.export_json('$(DB)', '$(SQL)'))"

auto-export:
	@echo "Smart auto-export..."
	cd backend && uv run python -c "from app.workflows.export_workflow import export_workflow; import asyncio; asyncio.run(export_workflow.smart_export('$(DB)', '$(SQL)'))"
```

## 使用示例

### 快速导出示例
```bash
# 导出用户数据
make export-csv DB=mydb SQL="SELECT * FROM users"

# 智能导出订单数据
make auto-export DB=mydb SQL="SELECT * FROM orders WHERE created_at > '2024-01-01'"

# 查看导出统计
export-stats
```

### 开发流程集成
```bash
# 测试查询并自动导出结果
make test-query DB=testdb SQL="SELECT COUNT(*) FROM users"

# 生成测试数据导出
make auto-export DB=testdb SQL="SELECT * FROM test_data LIMIT 1000"
```

## AI建议信息

当使用 `auto-export` 命令时，系统会显示AI建议信息：

```
🤖 AI导出分析结果:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 数据特征:
  • 行数: 1,234 行
  • 列数: 8 列
  • 复杂度: 0.45 (中等)

🎯 推荐格式: CSV
  • 置信度: 85%
  • 推荐原因: 数据结构简单，CSV格式处理速度更快

📈 预估信息:
  • 文件大小: ~0.12 MB
  • 导出时间: ~223 ms

🚀 自动化级别: ask (建议询问用户)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 高级功能

### 批量导出
创建导出配置文件进行批量导出：

```bash
# export-config.yaml
exports:
  - database: mydb
    sql: "SELECT * FROM users"
    format: csv
    output: users_export.csv

  - database: mydb
    sql: "SELECT * FROM orders WHERE status = 'completed'"
    format: json
    output: completed_orders.json
```

```bash
batch-export export-config.yaml
```

### 定时导出
结合系统定时任务实现定期导出：

```bash
# 每天凌晨导出数据
0 0 * * * /path/to/export-csv mydb "SELECT * FROM daily_report" > /path/to/logs/export.log 2>&1
```

### 导出模板
创建常用导出模板：

```bash
# 创建模板
create-export-template user_report "SELECT u.*, COUNT(o.id) as order_count FROM users u LEFT JOIN orders o ON u.id = o.user_id GROUP BY u.id"

# 使用模板
use-template user_report
```

## 错误处理

### 常见错误
- **连接失败**: 检查数据库连接配置
- **SQL语法错误**: 验证SQL语句语法
- **权限不足**: 确认数据库用户权限
- **文件写入失败**: 检查输出目录权限

### 日志记录
所有导出操作都会记录到日志文件：
```bash
# 查看导出日志
tail -f ~/.db_query/export.log
```