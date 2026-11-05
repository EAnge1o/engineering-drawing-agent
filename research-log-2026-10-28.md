# 选题调研日志

- **日期**：2026-10-28
- **项目**：2026 华为开发者大赛·智能体创新赛（南部赛区，高校组）
- **主题**：围绕比赛规则与 GitHub 开源竞品系统调研，寻找可复现、可量化的技术缺口
- **执行**：CodeArts 代码智能体（本机 win32 / git-bash）

---

## 1. 目标

为智能体赛道选定一个选题，满足：有实际价值、技术创新性、不与现有开源严重重复，并能在赛程内（截止 2026-11-16）完成可演示、可量化的作品。

## 2. 调研动作（实际执行）

| 步骤 | 动作 | 结果 |
|---|---|---|
| 2.1 | 抓取官方赛事页 `developer.huaweicloud.com/competition/information/1300000352` | 纯前端 SPA（HDCompetitionPortal），webfetch 仅返回"开发者大赛"，正文不可取；改用用户提供的赛事页文本核实规则 |
| 2.2 | 抓取 `github.com/col14m/cadrille` | ✅ 成功 |
| 2.3 | 抓取 `github.com/YUI-TIEN/img2cad` 及 `docs/DESIGN.md`、`ROADMAP.md`、`benchmark/README.md`、`skills/img2cad/{SKILL,MODELING,LESSONS}.md` | ✅ 成功（信息量最大） |
| 2.4 | 抓取 `research.nvidia.com/labs/lpr/gator/` | ✅ 成功（代码 Coming Soon） |
| 2.5 | 抓取 `github.com/anniedoris/CAD-Coder` | ✅ 成功 |
| 2.6 | 抓取 `github.com/SadilKhan/Text2CAD` | ✅ 成功 |
| 2.7 | 抓取 `github.com/IBM/AssetOpsBench` | ✅ 成功 |
| 2.8 | 尝试 DuckDuckGo HTML 搜索 | ❌ 网络不可达 |
| 2.9 | 尝试 `reqvire.com` | ❌ 网络不可达，未核验 |
| 2.10 | 尝试 `github.com/Cola-10/CAD-MLLM` | ❌ 404 |

> 网络策略：GitHub 与 NVIDIA 研究页可直连；搜索类与部分站点被拦截。

## 3. 规则核实结论

| 项目 | 结论 | 状态 |
|---|---|---|
| 赛道 | 智能体赛道（另有"小红书 Skill 创新"赛道） | ✅ 已核实 |
| 开发工具 | 必须用华为云码道为核心 AI 工具，并提交留痕（插件日志、AI 对话/Prompt 截图） | ✅ 已核实 |
| 评分 | 功能完备度 30 / 码道深度使用 25 / 专业贴合与创新 25 / 技术架构 15 / 交付 5 | ✅ 已核实 |
| 时间 | 报名截止 11-12；提交截止 11-16（每天 1 次）；区域赛答辩 11-21~27；决赛 12 月 | ✅ 已核实 |
| 交付物 | zip 含 ppt/ project/ video/ codearts_proof/ readme/ | ✅ 已核实 |
| 原创性 | 必须原创，禁止抄袭/侵权与跨组重复报名 | ✅ 已核实 |
| AgentArts / 指定模型 | 官方页未注明 | ⚠️ 待确认 |

关键推论：因"码道深度使用"占 25 分且需留痕，选题应能在一个码道会话内跑完"需求→架构→代码→测试"全流程。

## 4. 竞品矩阵（已核验）

| 竞品 | 方向 | 许可证 | 关键边界 |
|---|---|---|---|
| cadrille | 多模态(点云/图/文)→参数化 CAD | Apache-2.0 | 单次预测，SOTA；权重在 HF；无交互增量精化、无不确定性管理 |
| img2cad | 图/草图/图纸→可编辑 CAD（agent 工作流） | MIT | 已实现 observe→plan→build→compare→revise、confidence/unknowns、几何 gate、camera 拒绝、多视角 hull、revision 门控 |
| CAD-Coder | 图→CadQuery 代码 | 开源 | 需 4×H100 训练；单次生成；无验证闭环 |
| Text2CAD | 文本→CAD 序列 | 开源 | 需训练；无跨模态证据融合 |
| GATOR (NVIDIA) | 拍照→mesh 重建 + agentic 精化 | 代码未发布 | 输出 mesh 非 B-rep；不可复用 |
| AssetOpsBench (IBM) | 工业运维 Agent 基准 | Apache-2.0 | 运维诊断/编排评测，不同域 |
| Reqvire | 需求追踪与验证 | — | 未核验（站点不可达） |

## 5. 技术缺口（来自 img2cad 自证边界）

img2cad 的 `DESIGN.md`/`SKILL.md` 明确列出 "Current implementation boundary"：

1. 不做图像理解、不判定视觉正确性（视觉评审为定性输入，validator 只校验 hash）
2. 无可量化视觉 gate（silhouette 仅 advisory，真实照片 `reliable:false`）
3. dimension gate 过窄（仅 bounds/volume/hole/boss/平坦 face；自由曲面、倒角不查）
4. 无跨模态证据冲突检测/仲裁
5. 无参数化特征依赖图 / 变更影响分析
6. v1 spec 仅能表达"一个长方体+圆通孔"

**一句话缺口**：现有图→CAD 工作流是"单向、单次、定性"的；缺"多源证据联合约束 + 冲突仲裁 + 局部修改级联影响分析 + 确定性可量化验证闭环"，且该方向无需训练模型（VLM 观测 + OpenCASCADE 确定性推理）。

## 6. 候选方向 × 七维打分（5=最优；"开源竞争"高=竞争弱）

| # | 方向 | 竞争 | 缺口 | 创新 | 可行 | 可验 | 演示 | 契合 | 合计 |
|---|---|---|---|---|---|---|---|---|---|
| A | 多模态增量精化 CAD | 2 | 3 | 3 | 2 | 3 | 4 | 4 | 21 |
| B | 不确定性管理视觉工程 Agent | 3 | 4 | 4 | 2 | 3 | 4 | 4 | 24 |
| C | 垂直领域工程建模 | 3 | 3 | 3 | 3 | 4 | 3 | 4 | 23 |
| D | 工程变更影响分析+验证闭环 | 3 | 3 | 3 | 5 | 5 | 3 | 3 | 25 |
| **E** | **证据融合+约束影响图+确定性验证** | 4 | 5 | 5 | 3 | 5 | 4 | 5 | **31** |
| F | 维修诊断与方案 Agent | 2 | 3 | 3 | 3 | 3 | 4 | 4 | 22 |
| G | 图纸审查与设计一致性 Agent | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 28 |
| H | 需求变更影响分析 Agent | 2 | 3 | 3 | 5 | 4 | 3 | 3 | 23 |
| I | 实验流程复现与证据审计 | 5 | 4 | 4 | 4 | 4 | 3 | 3 | 27 |
| J | 现场巡检整改闭环 | 3 | 3 | 3 | 4 | 3 | 4 | 4 | 24 |
| K | 码道"证据链 CAD" Skill（meta） | 4 | 4 | 4 | 4 | 4 | 4 | 5 | 29 |

Top 3：**E(31) > K(29) > G(28)**

## 7. 推荐立项

### ★首选 E′「工程改型证据链 Agent」（E 的收敛版，规避视觉风险）
- 输入：已有参数化模型/STEP + 多源改型证据（文字尺寸、图纸标注、可选照片/测量）
- 核心机制：
  1. 证据分层 Spec（observed / inferred / user-confirmed / unknown + 来源 + 置信区间）
  2. 约束影响图（Constraint Dependency Graph）：改一个值→算出受影响特征集与需回归约束集
  3. 确定性验证闭环 gates（B-rep 有效性/体积/孔位 + 投影关键尺寸误差 + 公差，量化+阈值+自动回退）
- 指标：影响集 precision/recall、回归覆盖率、变更闭环率、冲突检出率/误报率、gate 假通过率
- 技术栈：Python + build123d/OpenCASCADE（本地、免费、快）+ networkx/rustworkx；可选华为云 ModelArts/盘古/OBS/DWS
- 开源组件声明：引用 img2cad(MIT)/cadrille(Apache-2.0)

### 次选 G「图纸/文档一致性审查 Agent」— 纯结构化，19 天风险最低
### 加成 K「把 E′/G 封装为码道 Skill」— 天然拿满"码道深度使用"

## 8. 待确认项

1. 是否必须部署 AgentArts？是否限用盘古/ModelArts？
2. 七维权重是否需调整（如"可行"更重）——当前打分为人工判断。
3. 下一步：出正式立项书 / 先跑通 E′ 最小原型 / 先落交付物模板。

---

## 附录：本次引用的关键来源

- https://developer.huaweicloud.com/competition/information/1300000352/circumstance （SPA，正文取自用户提供文本）
- https://github.com/col14m/cadrille
- https://github.com/YUI-TIEN/img2cad （+ docs/DESIGN.md, ROADMAP.md, benchmark/README.md, skills/img2cad/SKILL.md, MODELING.md, LESSONS.md）
- https://research.nvidia.com/labs/lpr/gator/
- https://github.com/anniedoris/CAD-Coder
- https://github.com/SadilKhan/Text2CAD
- https://github.com/IBM/AssetOpsBench