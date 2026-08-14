"""自动化导出工作流服务."""

from typing import Dict, List, Any, Optional
from datetime import datetime
from sqlmodel import Session
from app.models.database import DatabaseType
from app.models.schemas import QueryResult, ExportResult, ExportSuggestion
from app.services.query_wrapper import execute_query_with_service
from app.services.export_analyzer import export_analyzer
from app.models.query import QuerySource


class AutomatedExportWorkflow:
    """自动化导出工作流，实现一键"执行查询+智能分析+自动导出"."""

    def __init__(self):
        self.export_history: List[Dict[str, Any]] = []

    async def execute_and_export(
        self,
        session: Session,
        database_name: str,
        db_type: DatabaseType,
        url: str,
        sql: str,
        auto_export: bool = True,
        preferred_format: Optional[str] = None,
    ) -> ExportResult:
        """
        一键执行查询并导出.

        流程步骤：
        1. 执行SQL查询
        2. AI分析导出需求
        3. 自动选择最佳格式
        4. 生成导出内容
        5. 返回结果和导出建议

        Args:
            session: 数据库会话
            database_name: 数据库名称
            db_type: 数据库类型
            url: 数据库连接URL
            sql: SQL查询语句
            auto_export: 是否自动导出
            preferred_format: 首选格式

        Returns:
            ExportResult: 导出结果
        """
        start_time = datetime.now()

        # Step 1: 执行查询
        query_result = await self._execute_query(
            session, database_name, db_type, url, sql
        )

        # Step 2: AI分析导出需求
        export_suggestion = export_analyzer.analyze_export_need(query_result)

        # Step 3: 确定导出格式
        export_format = self._determine_export_format(
            export_suggestion, preferred_format, auto_export
        )

        # Step 4: 生成导出数据
        export_data = self._generate_export_data(query_result, export_format)

        # 计算导出时间
        export_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # 记录历史
        self._record_export_history(
            database_name, sql, export_format, query_result.row_count, export_time_ms, True
        )

        return ExportResult(
            success=True,
            fileUrl=None,  # 前端将生成文件
            fileSize=len(export_data) if export_data else 0,
            format=export_format,
            rowCount=query_result.row_count,
            exportTimeMs=export_time_ms,
        )

    async def smart_export_suggestion(
        self,
        session: Session,
        database_name: str,
        db_type: DatabaseType,
        url: str,
        sql: str,
    ) -> ExportSuggestion:
        """
        智能导出建议生成（不执行查询）.

        Args:
            session: 数据库会话
            database_name: 数据库名称
            db_type: 数据库类型
            url: 数据库连接URL
            sql: SQL查询语句

        Returns:
            ExportSuggestion: 导出建议
        """
        # 执行查询获取结果
        query_result = await self._execute_query(
            session, database_name, db_type, url, sql
        )

        # 生成AI建议
        suggestion = export_analyzer.analyze_export_need(query_result)

        return suggestion

    async def _execute_query(
        self,
        session: Session,
        database_name: str,
        db_type: DatabaseType,
        url: str,
        sql: str,
    ) -> QueryResult:
        """执行SQL查询."""
        return await execute_query_with_service(
            session, database_name, db_type, url, sql, QuerySource.MANUAL
        )

    def _determine_export_format(
        self,
        export_suggestion: ExportSuggestion,
        preferred_format: Optional[str],
        auto_export: bool,
    ) -> str:
        """确定最佳导出格式."""
        # 如果用户指定了格式，使用用户选择的格式
        if preferred_format and preferred_format in ["csv", "json"]:
            return preferred_format

        # 如果自动导出，使用AI推荐的格式
        if auto_export:
            return export_suggestion.recommended_format

        # 默认使用推荐格式
        return export_suggestion.recommended_format

    def _generate_export_data(
        self, query_result: QueryResult, format: str
    ) -> str:
        """生成导出数据."""
        if format == "csv":
            return self._generate_csv_data(query_result)
        else:  # json
            return self._generate_json_data(query_result)

    def _generate_csv_data(self, query_result: QueryResult, format: str = "csv") -> str:
        """生成CSV格式数据.

        Args:
            query_result: 查询结果数据
            format: 导出格式（目前仅支持csv，为保持接口一致性保留）
        """
        # Format parameter is kept for API consistency but not used in CSV generation
        if query_result.row_count == 0:
            return ""

        # 生成CSV头部
        headers = query_result.columns
        csv_lines = [",".join([col.name for col in headers])]

        # 生成CSV数据行
        for row in query_result.rows:
            values = []
            for col in headers:
                value = row.get(col.name, "")
                # 处理特殊字符
                if value is None or value == "":
                    values.append("")
                else:
                    str_value = str(value)
                    # 如果包含特殊字符，用引号包裹
                    if any(char in str_value for char in [",", '"', "\n", "\r"]):
                        # 转义引号
                        str_value = str_value.replace('"', '""')
                        values.append(f'"{str_value}"')
                    else:
                        values.append(str_value)
            csv_lines.append(",".join(values))

        return "\n".join(csv_lines)

    def _generate_json_data(self, query_result: QueryResult, format: str = "json") -> str:
        """生成JSON格式数据.

        Args:
            query_result: 查询结果数据
            format: 导出格式（目前仅支持json，为保持接口一致性保留）

        Note:
            format 参数未使用，保留是为了接口一致性
        """
        import json

        # 转换数据为JSON友好格式
        json_data = []
        for row in query_result.rows:
            # 处理特殊值类型
            processed_row = {}
            for col in query_result.columns:
                value = row.get(col.name)
                # 处理None值
                if value is None:
                    processed_row[col.name] = None
                # 处理datetime对象
                elif hasattr(value, "isoformat"):
                    processed_row[col.name] = value.isoformat()
                else:
                    processed_row[col.name] = value
            json_data.append(processed_row)

        return json.dumps(json_data, ensure_ascii=False, indent=2)

    def _record_export_history(
        self,
        database_name: str,
        sql: str,
        format: str,
        row_count: int,
        export_time_ms: int,
        success: bool,
    ) -> None:
        """记录导出历史."""
        history_entry = {
            "timestamp": datetime.now().isoformat(),
            "database_name": database_name,
            "sql": sql,
            "format": format,
            "row_count": row_count,
            "export_time_ms": export_time_ms,
            "success": success,
        }

        self.export_history.append(history_entry)

        # 只保留最近50条记录
        if len(self.export_history) > 50:
            self.export_history = self.export_history[-50:]

    def get_export_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取导出历史记录."""
        return self.export_history[-limit:]

    def get_export_statistics(self) -> Dict[str, Any]:
        """获取导出统计信息."""
        if not self.export_history:
            return {
                "total_exports": 0,
                "csv_exports": 0,
                "json_exports": 0,
                "avg_export_time_ms": 0,
                "total_rows_exported": 0,
            }

        total_exports = len(self.export_history)
        csv_exports = sum(1 for h in self.export_history if h["format"] == "csv")
        json_exports = sum(1 for h in self.export_history if h["format"] == "json")

        avg_export_time = sum(h["export_time_ms"] for h in self.export_history) / total_exports
        total_rows = sum(h["row_count"] for h in self.export_history)

        return {
            "total_exports": total_exports,
            "csv_exports": csv_exports,
            "json_exports": json_exports,
            "avg_export_time_ms": round(avg_export_time, 2),
            "total_rows_exported": total_rows,
        }


# 全局导出工作流实例
export_workflow = AutomatedExportWorkflow()