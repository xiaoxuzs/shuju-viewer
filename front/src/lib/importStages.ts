const IMPORT_STAGE_LABELS: Record<string, string> = {
  queued: "排队中",
  fingerprint: "计算数据集指纹",
  init: "初始化导入",
  proteins: "导入蛋白",
  proteoforms: "导入蛋白形态",
  matches: "导入鉴定结果",
  finalize: "完成数据集登记",
  success: "导入完成",
  failed: "导入失败",
};

export function formatImportStageLabel(stage: string | null, stageLabel: string | null): string {
  if (stage && IMPORT_STAGE_LABELS[stage]) return IMPORT_STAGE_LABELS[stage];
  if (stageLabel && stageLabel.trim()) return stageLabel;
  return "导入中";
}

export function clampImportProgress(progress: number | null | undefined): number {
  if (progress === null || progress === undefined || Number.isNaN(progress)) return 0;
  return Math.max(0, Math.min(100, progress));
}
