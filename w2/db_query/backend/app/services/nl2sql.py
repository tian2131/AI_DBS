"""Natural Language to SQL conversion service (mock for testing/demo)."""

from app.models.database import DatabaseType
import logging
import re

logger = logging.getLogger(__name__)


class NaturalLanguageToSQLService:
    """Service for converting natural language queries to SQL (mock mode)."""

    def __init__(self):
        """Initialize service."""
        # Mock mode - no API needed
        self.is_mock = True

    def _parse_query(
        self, user_prompt: str, metadata: dict, db_type: DatabaseType
    ) -> dict[str, str]:
        """Parse natural language and generate SQL using simple rules.

        Args:
            user_prompt: Natural language query
            metadata: Database schema metadata dictionary
            db_type: Database type (PostgreSQL or MySQL)

        Returns:
            Dict with 'sql' and 'explanation' keys
        """
        # Get first table name from metadata
        tables = metadata.get("tables", [])
        if not tables:
            raise ValueError("No tables found in metadata")

        table_name = tables[0]["name"]
        schema_name = tables[0].get("schemaName", "public" if db_type == DatabaseType.POSTGRESQL else "")

        # Build identifier based on database type
        if db_type == DatabaseType.MYSQL:
            identifier = f"`{table_name}`"
        else:
            identifier = f'"{schema_name}"."{table_name}"'

        # Simple pattern matching
        prompt_lower = user_prompt.lower()

        # 1. Count queries - "数量", "count", "有多少"
        if any(kw in prompt_lower for kw in ["数量", "count", "有多少", "多少条", "总共"]):
            return {
                "sql": f"SELECT COUNT(*) as count FROM {identifier}",
                "explanation": f"统计 {table_name} 表的记录数量"
            }

        # 2. First/Top queries - "前", "top", "first"
        top_match = re.search(r"(?:前|top|first|最近)\s*(\d+)", prompt_lower)
        limit = 10
        if top_match:
            limit = int(top_match.group(1))
        else:
            limit = 10  # Default limit

        # 3. WHERE clause detection
        where_clause = ""
        columns = tables[0].get("columns", [])

        # Check for specific column conditions
        for col in columns:
            col_name = col["name"].lower()
            col_type = col.get("dataType", "").lower()

            # Number comparisons
            if col_type in ["integer", "int", "bigint", "decimal", "float", "double"]:
                # Greater than
                gt_match = re.search(rf"{col_name}\s*[>大于]\s*(\d+)", prompt_lower)
                if gt_match:
                    where_clause = f'WHERE "{col_name}" > {gt_match.group(1)}'
                    break
                # Less than
                lt_match = re.search(rf"{col_name}\s*[<小于]\s*(\d+)", prompt_lower)
                if lt_match:
                    where_clause = f'WHERE "{col_name}" < {lt_match.group(1)}'
                    break

        # 4. ORDER BY detection
        order_clause = ""
        if "最新" in prompt_lower or "最近" in prompt_lower:
            # Look for date/time column
            for col in columns:
                col_type = col.get("dataType", "").lower()
                if "date" in col_type or "time" in col_type:
                    order_clause = f'ORDER BY "{col["name"]}" DESC'
                    break
        elif "最旧" in prompt_lower or "最早" in prompt_lower:
            for col in columns:
                col_type = col.get("dataType", "").lower()
                if "date" in col_type or "time" in col_type:
                    order_clause = f'ORDER BY "{col["name"]}" ASC'
                    break

        # Build final SQL
        sql_parts = [f"SELECT * FROM {identifier}"]
        if where_clause:
            sql_parts.append(where_clause)
        if order_clause:
            sql_parts.append(order_clause)
        sql_parts.append(f"LIMIT {limit}")

        sql = " ".join(sql_parts)

        # Generate explanation
        explanation = f"Generated SQL for: {user_prompt}"
        if "数量" in prompt_lower or "count" in prompt_lower:
            explanation = f"统计 {table_name} 的记录数量"
        elif top_match:
            explanation = f"查询 {table_name} 的前 {limit} 条记录"

        return {"sql": sql, "explanation": explanation}

    async def generate_sql(
        self, user_prompt: str, metadata: dict, db_type: DatabaseType = DatabaseType.POSTGRESQL
    ) -> dict[str, str]:
        """Convert natural language to SQL query (mock mode).

        Args:
            user_prompt: Natural language query
            metadata: Database schema metadata dictionary
            db_type: Database type (PostgreSQL or MySQL)

        Returns:
            Dict with 'sql' and 'explanation' keys
        """
        try:
            result = self._parse_query(user_prompt, metadata, db_type)
            logger.info(f"Generated SQL (mock): {result['sql']}")
            return result
        except Exception as e:
            logger.error(f"Failed to generate SQL: {str(e)}")
            raise Exception(f"Failed to generate SQL: {str(e)}")


# Global instance
nl2sql_service = NaturalLanguageToSQLService()