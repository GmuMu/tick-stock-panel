# TASK-0704 Regime UI

状态：DONE（2026-09-05）

## 实现

- `frontend/src/lib/api.ts` 增加 `DataQualityInfo`、覆盖缺口和资金效应类型。
- `frontend/src/pages/Regime.tsx` 在页面头部展示覆盖比例、质量状态、缺失日期和待重算日期。
- 最新日概览增加资金效应卡，综合分趋势图增加资金评分曲线。
- 日级质量异常会在最新状态卡中提示；原有情绪阶段、主线和趋势视图保持不变。

## 验收

- 前端 TypeScript/Vite 构建（使用仓库已有依赖时执行）
- 页面路由：`/regime`
- 后端质量接口：`/api/regime/coverage`、`/history`、`/latest`、`/states`
