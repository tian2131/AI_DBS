"""AI智能导出建议分析器服务."""

from typing import Dict, List, Any, Optional
from app.models.schemas import QueryResult, QueryColumn
from datetime import datetime


class ExportAnalysis:
    """导出分析结果数据结构."""

    def __init__(
        self,
        row_count: int,
        column_count: int,
        data_type_distribution: Dict[str, int],
        has_null_values: bool,
        has_special_characters: bool,
        estimated_csv_size_bytes: int,
        estimated_json_size_bytes: int,
        complexity_score: float,
    ):
        self.row_count = row_count
        self.column_count = column_count
        self.data_type_distribution = data_type_distribution
        self.has_null_values = has_null_values
        self.has_special_characters = has_special_characters
        self.estimated_csv_size_bytes = estimated_csv_size_bytes
        self.estimated_json_size_bytes = estimated_json_size_bytes
        self.complexity_score = complexity_score  # 0-1，越高越复杂


class ExportSuggestion:
    """导出建议数据结构."""

    def __init__(
        self,
        recommended_format: str,
        confidence_score: float,
        reasoning: str,
        estimated_size_mb: float,
        export_time_estimate_ms: int,
        automation_suggestion: str,
        alternative_formats: List[str],
    ):
        self.recommended_format = recommended_format  # "csv" or "json"
        self.confidence_score = confidence_score  # 0-1，建议置信度
        self.reasoning = reasoning  # 建议原因
        self.estimated_size_mb = estimated_size_mb
        self.export_time_estimate_ms = export_time_estimate_ms
        self.automation_suggestion = automation_suggestion  # "auto", "manual", "ask"
        self.alternative_formats = alternative_formats


class ExportAnalyzer:
    """AI智能导出建议分析器."""

    def __init__(self):
        # 配置参数
        self.small_dataset_threshold = 1000  # 小数据集阈值
        self.large_dataset_threshold = 10000  # 大数据集阈值
        self.auto_export_small_threshold = 500  # 自动导出的小数据阈值
        self.csv_efficiency_ratio = 0.7  # CSV相比JSON的大小比例

    def analyze_export_need(self, query_result: QueryResult) -> ExportSuggestion:
        """
        分析查询结果，生成智能导出建议.

        分析因素：
        - 数据量大小（行数）
        - 数据类型分布（字符串、数字、日期等）
        - 列数和数据复杂度
        - 查询执行时间（用于估算导出时间）

        Args:
            query_result: 查询结果数据

        Returns:
            ExportSuggestion: 智能导出建议
        """
        # 第一步：分析数据特征
        analysis = self._analyze_data_features(query_result)

        # 第二步：推荐最佳格式
        recommended_format = self._recommend_format(analysis)

        # 第三步：生成建议
        suggestion = self._generate_suggestion(analysis, recommended_format)

        return suggestion

    def _analyze_data_features(self, query_result: QueryResult) -> ExportAnalysis:
        """深度分析查询结果的数据特征."""
        row_count = query_result.row_count
        column_count = len(query_result.columns)

        # 分析数据类型分布
        data_type_distribution = {}
        for col in query_result.columns:
            dtype = col.data_type.lower()
            data_type_distribution[dtype] = data_type_distribution.get(dtype, 0) + 1

        # 检查特殊值
        has_null_values = self._check_null_values(query_result.rows)
        has_special_characters = self._check_special_characters(query_result.rows)

        # 估算文件大小
        estimated_csv_size = self._estimate_csv_size(row_count, column_count, query_result.rows)
        estimated_json_size = self._estimate_json_size(row_count, column_count, query_result.rows)

        # 计算复杂度分数
        complexity_score = self._calculate_complexity_score(
            row_count, column_count, data_type_distribution, has_null_values, has_special_characters
        )

        return ExportAnalysis(
            row_count=row_count,
            column_count=column_count,
            data_type_distribution=data_type_distribution,
            has_null_values=has_null_values,
            has_special_characters=has_special_characters,
            estimated_csv_size_bytes=estimated_csv_size,
            estimated_json_size_bytes=estimated_json_size,
            complexity_score=complexity_score,
        )

    def _check_null_values(self, rows: List[Dict[str, Any]]) -> bool:
        """检查数据中是否包含NULL值."""
        for row in rows[:100]:  # 只检查前100行以提升性能
            if any(value is None for value in row.values()):
                return True
        return False

    def _check_special_characters(self, rows: List[Dict[str, Any]]) -> bool:
        """检查数据中是否包含特殊字符（逗号、引号、换行等）."""
        special_chars = [",", '"', "\n", "\r"]
        for row in rows[:100]:  # 只检查前100行以提升性能
            for value in row.values():
                if isinstance(value, str):
                    if any(char in value for char in special_chars):
                        return True
        return False

    def _estimate_csv_size(self, row_count: int, column_count: int, rows: List[Dict[str, Any]]) -> int:
        """估算CSV文件大小."""
        if row_count == 0:
            return 0

        # 采样计算平均行大小
        sample_size = min(100, len(rows))
        total_sample_size = 0

        for i in range(sample_size):
            row = rows[i]
            # 估算CSV行大小：逗号 + 引号 + 值大小
            row_size = sum(len(str(value)) + 3 for value in row.values())  # +3 for quotes and comma
            row_size += column_count - 1  # commas between values
            row_size += 1  # newline
            total_sample_size += row_size

        avg_row_size = total_sample_size / sample_size if sample_size > 0 else 0
        return int(avg_row_size * row_count) + 100  # +100 for header

    def _estimate_json_size(self, row_count: int, column_count: int, rows: List[Dict[str, Any]]) -> int:
        """估算JSON文件大小."""
        if row_count == 0:
            return 0

        # JSON通常比CSV大30-50%
        csv_size = self._estimate_csv_size(row_count, column_count, rows)
        return int(csv_size * 1.4)  # JSON大约比CSV大40%

    def _calculate_complexity_score(
        self,
        row_count: int,
        column_count: int,
        data_type_distribution: Dict[str, int],
        has_null_values: bool,
        has_special_characters: bool,
    ) -> float:
        """计算数据复杂度分数（0-1）。"""
        # 基础复杂度
        complexity = 0.0

        # 数据量复杂度（最大0.3）
        if row_count > self.large_dataset_threshold:
            complexity += 0.3
        elif row_count > self.small_dataset_threshold:
            complexity += 0.15

        # 列数复杂度（最大0.2）
        if column_count > 20:
            complexity += 0.2
        elif column_count > 10:
            complexity += 0.1

        # 数据类型复杂度（最大0.2）
        string_types = sum(1 for dtype in data_type_distribution.keys() if "varchar" in dtype or "text" in dtype)
        if string_types > 5:
            complexity += 0.2
        elif string_types > 2:
            complexity += 0.1

        # 特殊值复杂度（最大0.3）
        if has_special_characters:
            complexity += 0.2
        if has_null_values:
            complexity += 0.1

        return min(complexity, 1.0)

    def _recommend_format(self, analysis: ExportAnalysis) -> str:
        """基于分析推荐最佳导出格式."""
        # 推荐逻辑：
        # 1. 小数据集且数据简单 -> CSV（更小、更快）
        # 2. 有特殊字符 -> JSON（更好的兼容性）
        # 3. 大数据集 -> CSV（更小的文件大小）
        # 4. 复杂数据类型 -> JSON（更好的类型保留）

        if analysis.has_special_characters:
            return "json"  # JSON处理特殊字符更好

        if analysis.complexity_score > 0.6:
            return "json"  # 复杂数据类型用JSON更好

        if analysis.row_count > self.large_dataset_threshold:
            return "csv"  # 大数据集CSV更小

        if analysis.row_count < self.small_dataset_threshold:
            return "csv"  # 小数据集CSV更快

        # 默认推荐CSV
        return "csv"

    def _generate_suggestion(self, analysis: ExportAnalysis, recommended_format: str) -> ExportSuggestion:
        """生成完整的导出建议."""
        # 计算置信度
        confidence = self._calculate_confidence(analysis, recommended_format)

        # 生成推荐原因
        reasoning = self._generate_reasoning(analysis, recommended_format)

        # 估算导出时间（基于查询执行时间的启发式方法）
        export_time_estimate = self._estimate_export_time(analysis)

        # 生成自动化建议
        automation = self._suggest_automation(analysis)

        # 备选格式
        alternatives = ["json"] if recommended_format == "csv" else ["csv"]

        # 转换文件大小为MB
        estimated_size_mb = analysis.estimated_csv_size_bytes / (1024 * 1024) if recommended_format == "csv" else analysis.estimated_json_size_bytes / (1024 * 1024)

        return ExportSuggestion(
            recommended_format=recommended_format,
            confidence_score=confidence,
            reasoning=reasoning,
            estimated_size_mb=round(estimated_size_mb, 2),
            export_time_estimate_ms=export_time_estimate,
            automation_suggestion=automation,
            alternative_formats=alternatives,
        )

    def _calculate_confidence(self, analysis: ExportAnalysis, recommended_format: str) -> float:
        """计算推荐置信度."""
        # 如果有特殊字符推荐JSON，置信度很高
        if analysis.has_special_characters and recommended_format == "json":
            return 0.9

        # 如果复杂度高推荐JSON，置信度较高
        if analysis.complexity_score > 0.7 and recommended_format == "json":
            return 0.85

        # 如果大数据集推荐CSV，置信度很高
        if analysis.row_count > self.large_dataset_threshold and recommended_format == "csv":
            return 0.9

        # 如果小数据集推荐CSV，置信度中等
        if analysis.row_count < self.small_dataset_threshold and recommended_format == "csv":
            return 0.7

        # 默认置信度
        return 0.6

    def _generate_reasoning(self, analysis: ExportAnalysis, recommended_format: str) -> str:
        """生成推荐原因."""
        reasons = []

        if analysis.has_special_characters:
            reasons.append("数据包含特殊字符，JSON格式兼容性更好")

        if analysis.complexity_score > 0.7:
            reasons.append("数据结构较复杂，JSON能更好保留类型信息")

        if analysis.row_count > self.large_dataset_threshold:
            reasons.append(f"大数据集（{analysis.row_count:,}行），CSV文件更小，传输更快")

        if analysis.row_count < self.small_dataset_threshold:
            reasons.append(f"小数据集（{analysis.row_count:,}行），CSV格式处理速度更快")

        if analysis.estimated_csv_size_bytes > 10 * 1024 * 1024:  # > 10MB
            reasons.append("预计文件较大，推荐CSV以节省空间")

        if not reasons:
            reasons.append("基于数据特征和性能考虑的推荐")

        return "。".join(reasons) + "。"

    def _estimate_export_time(self, analysis: ExportAnalysis) -> int:
        """估算导出时间（毫秒）。"""
        # 基于行数的简单估算
        base_time = 100  # 基础时间100ms
        per_row_time = 0.1  # 每行0.1ms

        estimated_time = base_time + (analysis.row_count * per_row_time)

        # 考虑复杂度
        complexity_multiplier = 1 + analysis.complexity_score
        estimated_time *= complexity_multiplier

        return int(estimated_time)

    def _suggest_automation(self, analysis: ExportAnalysis) -> str:
        """建议是否适合自动化导出."""
        # 小数据集且简单 -> 自动导出
        if analysis.row_count < self.auto_export_small_threshold and analysis.complexity_score < 0.3:
            return "auto"

        # 中等数据集 -> 询问用户
        if analysis.row_count < self.small_dataset_threshold:
            return "ask"

        # 大数据集或复杂 -> 手动选择
        return "manual"


# 全局导出分析器实例
export_analyzer = ExportAnalyzer()