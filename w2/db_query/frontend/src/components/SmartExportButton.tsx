/** Smart export button with AI-powered suggestions and automation. */

import React, { useState, useEffect } from "react";
import {
  Button,
  Space,
  Dropdown,
  Menu,
  message,
  Modal,
  Tag,
  Spin,
  Tooltip,
  Alert,
  Typography,
} from "antd";
import {
  DownloadOutlined,
  FileTextOutlined,
  FileTextTwoTone,
  ThunderboltOutlined,
  CheckCircleOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";
import { QueryResult } from "../types/query";

const { Text, Paragraph } = Typography;

interface ExportSuggestion {
  recommendedFormat: "csv" | "json";
  confidenceScore: number;
  reasoning: string;
  estimatedSizeMb: number;
  exportTimeEstimateMs: number;
  automationSuggestion: "auto" | "ask" | "manual";
  alternativeFormats: string[];
}

interface SmartExportButtonProps {
  queryResult: QueryResult | null;
  databaseName: string | null;
  onExportComplete?: (format: string, rowCount: number) => void;
  loading?: boolean;
}

export const SmartExportButton: React.FC<SmartExportButtonProps> = ({
  queryResult,
  databaseName,
  onExportComplete,
  loading = false,
}) => {
  const [exportSuggestion, setExportSuggestion] = useState<ExportSuggestion | null>(null);
  const [showSuggestion, setShowSuggestion] = useState(false);
  const [loadingSuggestion, setLoadingSuggestion] = useState(false);
  const [autoExportPending, setAutoExportPending] = useState(false);

  // 当查询结果改变时，自动获取AI导出建议
  useEffect(() => {
    if (queryResult && databaseName && queryResult.rowCount > 0) {
      fetchExportSuggestion();
    } else {
      setExportSuggestion(null);
      setShowSuggestion(false);
    }
  }, [queryResult, databaseName]);

  const fetchExportSuggestion = async () => {
    if (!queryResult || !databaseName) return;

    setLoadingSuggestion(true);
    try {
      // 这里我们模拟AI建议，实际应该调用后端API
      const suggestion = await simulateExportSuggestion(queryResult);
      setExportSuggestion(suggestion);

      // 根据自动化建议决定是否自动显示
      if (suggestion.automationSuggestion === "auto") {
        setShowSuggestion(true);
        setTimeout(() => {
          handleAutoExport(suggestion.recommendedFormat);
        }, 1500); // 1.5秒后自动导出，给用户时间看到建议
      } else if (suggestion.automationSuggestion === "ask") {
        setShowSuggestion(true);
      }
    } catch (error) {
      console.error("Failed to get export suggestion:", error);
    } finally {
      setLoadingSuggestion(false);
    }
  };

  // 模拟AI导出建议（实际应该调用后端API）
  const simulateExportSuggestion = async (result: QueryResult): Promise<ExportSuggestion> => {
    // 模拟网络延迟
    await new Promise(resolve => setTimeout(resolve, 500));

    const hasSpecialChars = result.rows.some(row =>
      Object.values(row).some(val =>
        typeof val === 'string' && /[,\"\n\r]/.test(val)
      )
    );

    const recommendedFormat = hasSpecialChars || result.columns.length > 10 ? "json" : "csv";
    const confidenceScore = hasSpecialChars ? 0.9 : 0.7;
    const estimatedSize = result.rowCount * result.columns.length * 50; // 简单估算

    return {
      recommendedFormat,
      confidenceScore,
      reasoning: hasSpecialChars
        ? "数据包含特殊字符，JSON格式兼容性更好。"
        : `基于${result.rowCount.toLocaleString()}行数据的分析，推荐使用${recommendedFormat.toUpperCase()}格式。`,
      estimatedSizeMb: estimatedSize / (1024 * 1024),
      exportTimeEstimateMs: Math.round(result.rowCount * 0.1 + 100),
      automationSuggestion: result.rowCount < 500 ? "auto" : result.rowCount < 1000 ? "ask" : "manual",
      alternativeFormats: recommendedFormat === "csv" ? ["json"] : ["csv"],
    };
  };

  const handleAutoExport = (format: string) => {
    if (!queryResult) return;

    setAutoExportPending(true);
    setTimeout(() => {
      // 执行导出
      if (format === "csv") {
        exportToCSV();
      } else {
        exportToJSON();
      }

      setAutoExportPending(false);
      message.success(`已自动导出为 ${format.toUpperCase()} 格式`);

      if (onExportComplete) {
        onExportComplete(format, queryResult.rowCount);
      }
    }, exportSuggestion?.exportTimeEstimateMs || 100);
  };

  const exportToCSV = () => {
    if (!queryResult) return;

    const headers = queryResult.columns.map((col) => col.name);
    const csvRows = [headers.join(",")];

    queryResult.rows.forEach((row) => {
      const values = headers.map((header) => {
        const value = row[header];
        if (value === null || value === undefined) return "";
        const stringValue = String(value);
        if (stringValue.includes(",") || stringValue.includes('"') || stringValue.includes("\n")) {
          return `"${stringValue.replace(/"/g, '""')}"`;
        }
        return stringValue;
      });
      csvRows.push(values.join(","));
    });

    const csvContent = csvRows.join("\n");
    downloadFile(csvContent, `${databaseName}_export.csv`, "text/csv;charset=utf-8;");
  };

  const exportToJSON = () => {
    if (!queryResult) return;

    const jsonContent = JSON.stringify(queryResult.rows, null, 2);
    downloadFile(jsonContent, `${databaseName}_export.json`, "application/json;charset=utf-8;");
  };

  const downloadFile = (content: string, filename: string, mimeType: string) => {
    const blob = new Blob([content], { type: mimeType });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const handleExportFormat = (format: string) => {
    if (format === "csv") {
      exportToCSV();
    } else if (format === "json") {
      exportToJSON();
    }

    if (onExportComplete && queryResult) {
      onExportComplete(format, queryResult.rowCount);
    }
  };

  const exportMenu = (
    <Menu
      onClick={({ key }) => handleExportFormat(key)}
      items={[
        {
          key: "csv",
          label: (
            <Space>
              <FileTextOutlined />
              <span>Export as CSV</span>
              {exportSuggestion?.recommendedFormat === "csv" && (
                <Tag color="green">Recommended</Tag>
              )}
            </Space>
          ),
        },
        {
          key: "json",
          label: (
            <Space>
              <FileTextTwoTone />
              <span>Export as JSON</span>
              {exportSuggestion?.recommendedFormat === "json" && (
                <Tag color="green">Recommended</Tag>
              )}
            </Space>
          ),
        },
      ]}
    />
  );

  if (!queryResult) {
    return (
      <Button disabled icon={<DownloadOutlined />}>
        Export
      </Button>
    );
  }

  const getConfidenceColor = (score: number) => {
    if (score >= 0.8) return "green";
    if (score >= 0.6) return "orange";
    return "red";
  };

  return (
    <>
      <Space direction="vertical" size="small" style={{ width: "100%" }}>
        <Space>
          {exportSuggestion && showSuggestion && (
            <Tooltip title={exportSuggestion.reasoning}>
              <Tag
                color={getConfidenceColor(exportSuggestion.confidenceScore)}
                icon={<CheckCircleOutlined />}
              >
                AI建议: {exportSuggestion.recommendedFormat.toUpperCase()}
                {exportSuggestion.confidenceScore >= 0.8 && (
                  <span style={{ marginLeft: 4 }}>({Math.round(exportSuggestion.confidenceScore * 100)}% 置信度)</span>
                )}
              </Tag>
            </Tooltip>
          )}

          <Dropdown overlay={exportMenu} disabled={loading || autoExportPending}>
            <Button
              type="primary"
              icon={autoExportPending ? <Spin size="small" /> : <DownloadOutlined />}
              loading={loading}
            >
              Export
            </Button>
          </Dropdown>

          {exportSuggestion && (
            <Button
              type="default"
              icon={<ThunderboltOutlined />}
              onClick={() => handleAutoExport(exportSuggestion.recommendedFormat)}
              disabled={loading || autoExportPending}
            >
              Auto Export
            </Button>
          )}
        </Space>

        {exportSuggestion && showSuggestion && (
          <Alert
            message={
              <Space direction="vertical" size="small" style={{ width: "100%" }}>
                <Text strong>
                  <ThunderboltOutlined style={{ color: "#1890ff", marginRight: 8 }} />
                  AI智能导出建议
                </Text>
                <Paragraph style={{ margin: 0 }}>
                  <InfoCircleOutlined style={{ color: "#1890ff", marginRight: 8 }} />
                  {exportSuggestion.reasoning}
                </Paragraph>
                <Space size="large">
                  <Text type="secondary">
                    预估大小: ~{exportSuggestion.estimatedSizeMb.toFixed(2)} MB
                  </Text>
                  <Text type="secondary">
                    预估时间: ~{exportSuggestion.exportTimeEstimateMs} ms
                  </Text>
                  <Text type="secondary">
                    置信度: {Math.round(exportSuggestion.confidenceScore * 100)}%
                  </Text>
                </Space>
              </Space>
            }
            type="info"
            showIcon={false}
            closable
            onClose={() => setShowSuggestion(false)}
          />
        )}

        {autoExportPending && (
          <Alert
            message={
              <Space>
                <Spin size="small" />
                <Text>正在自动导出为 {exportSuggestion?.recommendedFormat.toUpperCase()} 格式...</Text>
              </Space>
            }
            type="success"
            showIcon={false}
          />
        )}
      </Space>
    </>
  );
};