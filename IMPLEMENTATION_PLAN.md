# 专利工作台实施规划

日期：2026-11-16。状态：规划，尚未实现或验证端到端流程。

## 1. 目标与已确定选择

输入技术交底、论文、代码说明、实验结果与已有图纸；先检索专利与论文摘要，再获取重点全文、梳理技术路线、形成权利要求和说明书，输出供专利事务所继续修改的 DOCX。

- 一个任务中台，七个专业 Agent，共享项目数据；模块化单体，单机起步。
- React + TypeScript 前端；Python + FastAPI 后端；LangGraph 编排；PostgreSQL + pgvector；本地文件目录。
- OfficeCLI 作为唯一默认 DOCX 写入工具，通过其原生 MCP 接入。上一版建议的 python-docx/docxtpl 不再作为并行主写入路径。
- 知网是优先适配的中文论文平台；专利检索独立接 EPO OPS 与公开专利来源，避免把知网当成完整专利检索库。
- 首期使用一个模型完成不同角色工作；提取、检索与审阅可以独立替换模型，暂不开发复杂模型路由。
- 当前只输出本地文件，不自动向事务所发送文件、不自动提交申请。

## 2. 当前核查结果与待验证点

本机已执行 `officecli --version`，结果为 1.0.160；`officecli help mcp` 确认 `officecli mcp` 可启动 stdio MCP 服务。`help docx revision/comment` 列出了修订和批注接口，包括批注回复、解决状态，以及明确的修订创建操作。

这些是命令帮助核查，不等于真实事务所 DOCX 已通过往返测试。以下仍需实测：中文多节模板、公式和域、编号、批注线程、既有格式修订、Word/WPS 分页。

OfficeCLI 的 `revision.beforeLost` 提示某些格式修改前快照不能通过 dump→batch 重建保留。因此返稿应复制原 DOCX 后局部编辑，不抽取纯文本后重建全文。resident 模式交给其他程序前必须 save/close；DOCX 的 refresh 帮助明确要求 Windows + Word。

知网公开《会员服务使用协议》第二部分 6.2 限制程序下载，6.3 限制向第三方传播下载文章；具体机构合同可能不同。本次未取得用户账号、机构合同或授权 API，也未登录或下载。不能承诺普通账号直接实现无人值守全文下载。当前可交付路径为摘要/题录导入与检索辅助、打开文献页面、用户下载后自动入库；明确支持自动获取的机构接口另作适配。

## 3. 实际工作流

1. 材料理解：提取技术问题、步骤、设备、输入输出、参数和效果，保留材料位置；缺失信息列入工作说明。
2. 摘要检索：专利与论文查询可并行；保存来源、查询式、检索时间、原始摘要和缺失字段。
3. 初筛：按技术问题、技术手段和应用条件判断相关性；优先获取高相关项，也保留代表性技术分支，避免只看关键词排名。
4. 全文获取：已有文件 → 开放全文 → 已授权平台接口 → 人工下载后自动入库。知网具体按账号可用授权路径执行。
5. 全文解析：PDF/HTML 经 Docling 解析；保留原文件、页码、段落、表格和图位置。CAJ 单独保存，未验证解析能力前标为待转换，不改后缀冒充 PDF。
6. 技术路线梳理：分别形成用户方案和文献方案；提取输入、处理步骤、输出、条件、效果，比较相同与区别技术特征。
7. 权利要求设计：形成独立项与从属项骨架、特征关系及说明书展开要求。用户可以随时调整保护重点。
8. 说明书与附图：写作和绘图读取同一版术语与技术特征，可并行生成；没有证据的数值不补造。
9. 审阅修正：程序检查编号、引用与缺失对象；审阅 Agent 检查技术与文本逻辑，按问题定位回退。默认最多两轮自动修正，其余保留在工作报告。
10. Word 装配：复制事务所模板，OfficeCLI 写入内容与图，保存，结构检查和逐页预览。
11. 事务所返稿：导入为新版本，读取批注/修订，在其副本中有针对性地修改，输出修订稿和回复说明。

摘要仅用于相关性筛选与初步技术地图。只有摘要的记录保持 abstract_only，不能生成全文级对比结论；下载失败也不等于文献不存在。

## 4. 七个 Agent 的实现

每个 Agent 是一个 LangGraph 节点或小子图，由角色提示词、输入数据类型、限定工具列表、输出数据类型和有限调用循环组成。不是独立微服务，也不必对应独立模型。

| Agent | 输入 | 工具 | 输出 |
|---|---|---|---|
| 材料理解 | 原始交底与文件定位 | 文档解析、项目材料查询 | 技术事实、术语、技术步骤、来源定位、待补问题 |
| 摘要检索与筛选 | 技术特征、检索范围 | search_papers、search_patents、import_bibliography | 候选文献、原始摘要、相关理由、获取优先级 |
| 全文获取 | 入选记录与访问途径 | resolve_fulltext、open_record、download_fulltext、ingest_download | 文件 ID、来源记录、访问状态和失败原因 |
| 技术路线与权利要求 | 用户事实与文献全文证据 | 项目内检索、读取证据片段 | 技术路线、特征对照、权利要求骨架、支持关系 |
| 说明书写作 | 特征、权利要求、实施例与术语 | 项目材料查询 | 分节正文、摘要、附图说明、段落关联 |
| 图表 | 流程、模块、标号和原始数据 | Graphviz、Matplotlib | 可编辑图源、图片、图号、数据来源 |
| 审阅与 Word 编辑 | 正文、图、来源、模板或返稿 | 确定性检查、OfficeCLI MCP | 初稿/修订稿、预览、问题清单、批注回复 |

审阅与编辑在同一 Agent 内分两个阶段执行：先形成问题清单，再调用文档工具；该节点是 DOCX 的唯一写入者。其他 Agent 输出结构化内容，不同时编辑 Word 文件。

模型结果用普通 Pydantic 类型校验。一次格式修复仍不满足结构则保存错误并让该节点等待处理；不无限重问。工具网络超时单独重试。主流程路由由程序决定，Agent 只在自己的任务范围内决定查询和补充读取。

生成节点输入包含 project_id、input_version、目标、相关资料 ID、术语和必要片段；输出包含内容、来源 ID、缺失信息和修改涉及对象。模型自行打分不作为事实正确性的证明。

## 5. MCP 接入

第一版有三个 MCP 连接：

1. research-mcp：项目自建的薄适配层，统一暴露论文/专利检索、题录导入、全文定位和获取；底层按平台调用 API 或授权连接器。
2. Playwright MCP：本地专用浏览器，用于授权允许的页面交互、打开文献和人工登录接管；适配成熟后尽量由确定性页面操作执行固定步骤。
3. OfficeCLI MCP：直接启动本机 `officecli mcp`，复用原生文档工具，不重复包装整套 DOCX API。

第一版 FastAPI、Worker 和 MCP 客户端运行在用户 Windows 电脑上，数据库可放容器；浏览器与本地 Word 能力留在宿主机。stdio 子进程由本地 Worker 启动。不要在远程服务器里假设能直接读取用户电脑的浏览器登录态。以后远程部署再加本地连接服务，通过受认证的 Streamable HTTP 连接。

MCP 解决工具调用方式；平台账号授权是另外一层。远程 MCP 访问令牌不能直接充当知网或其他上游平台令牌。使用 MCP SDK 提供的协商与通信，不手写协议栈。

以下是拟实现接口，不是现有平台已经提供的 API：

| 工具 | 核心参数 | 返回 |
|---|---|---|
| search_papers | query、filters、cursor | records、next_cursor、来源及检索时间 |
| search_patents | query、classifications、date_filters、cursor | 公开记录、同族线索、摘要、日期 |
| import_bibliography | project_id、file_id | 导入的记录、未解析字段 |
| resolve_fulltext | record_id | 可用来源、访问途径、状态 |
| connect_source | provider | 登录页面/接管状态，不返回密码或 Cookie |
| open_record | record_id | 指定文献页面与人工操作状态 |
| download_fulltext | record_id、connection_id | 授权接口文件 ID 或待人工状态 |
| ingest_download | record_id、file_id | 格式校验、文献匹配、解析任务 ID |

工具返回结构化 JSON 和本地文件/资源 ID，不把 PDF 的 base64 或整篇长文本塞进模型上下文。后台可使用普通作业 ID 轮询长任务，不依赖实验性 MCP 扩展。

## 6. 知网连接与下载路径

- 专用浏览器配置保存登录态，用户首次在浏览器中完成个人或学校机构登录；验证码、扫码和二次认证交还用户。
- 密码不进入提示词；浏览器配置留在本机用户受限目录，不入 Git，不返回 Cookie 给模型。每个账号连接同一时间只由一个浏览器任务使用，避免 profile 冲突。
- 查询可从已授权元数据接口、平台导出的题录摘要，以及公开搜索得到的知网页面线索开始。未获取到摘要的记录保留空值，不补造。
- 原生知网全文自动获取以明确允许的机构/API 授权为前提，接口细节待取得后适配；本次未核实存在适用于用户的公开自助全文 API。
- 普通会员路径：系统生成获取清单并打开具体文献页面，用户下载到专用 inbox，后台等待文件完整后匹配题名/DOI/知网记录 ID，解析入库。人工环节结束后后续步骤自动继续。
- 需要额外扣费时显示文献与价格，由用户决定；不自动充值或购买。
- 登录过期、无全文权限、验证码、限流、仅 CAJ、下载到 HTML 登录页是不同状态，分别显示处理方式。某条失败不终止其他独立任务。
- 下载后校验真实格式、可解析性和题名/标识对应关系；预印本、正式论文和专利不同公开版本分别记录。
- 给事务所的交付包默认包含来源链接、书目信息和自己的对照分析；不自动附带知网账号下载的受限制全文。

## 7. 项目数据和文档版本

采用普通主键、外键、版本号和事务：projects、sources、source_passages、features、claims、sections、figures、document_versions、jobs。连接凭据存本机凭据存储/浏览器目录，数据库只保存连接引用。

source_passages 保存原始引文、页码/段落位置和原文语言；中文概述与原文分开。features 区分材料明确提供、用户待确认和 Agent 建议，避免把检索来的技术特征误当成用户已经实现的事实。

初稿阶段结构化正文用于组装 DOCX；导入事务所返稿后，该版 DOCX 是本轮编辑依据，解析数据只是索引，不能用旧数据库正文覆盖返稿。每次写入前检查版本；同一文件串行写。优先使用现有段落 ID/书签定位，没有时用文字和上下文匹配；定位多义就形成待处理问题，不猜段落。

审阅依据的段落与实际写入前内容一致才应用补丁，避免用户或事务所插入段落后修改错位置。插入删除后重新获取路径。普通版本检查与测试足够，不新增哈希、冻结合同或多级门禁。

## 8. Word 输出和返稿

新稿：事务所模板副本 → 填充章节与表格 → 嵌入附图 → 应用样式/编号 → save/close → 读取检查 → 页面预览。无模板先使用内部简洁模板，得到事务所模板后再适配。

文字、表格保留 Word 可编辑结构；公式优先 Word 公式；流程图嵌入图片时同时交付 SVG/DOT 图源。正文不混入来源台账、待补问题和开发注释。

返稿：保存收到文件 → 提取批注与修订 → 归类为技术事实、保护范围、表述或格式问题 → 输出逐条回复建议 → 在副本上用显式修订操作修改。不会默认接受或拒绝事务所已有修订。

OfficeCLI HTML/PNG 用于快速预览；最终样本在事务所实际使用的 Word/WPS 中核对。不把 HTML 预览等同于 Word 的实际分页。PDF 作为附属预览，可由已验证的 Word/LibreOffice 渲染路径生成；实际兼容性以选定环境实测为准。

如返稿中的复杂对象无法可靠保留，保留原件并输出指定位置的修改建议。不要静默删除批注、扁平化公式或把全文替换成新文档。

交付：专利草稿.docx；需要时提供带修订稿.docx；检索与技术对照.docx；问题与回复说明.docx；附图源文件；预览.pdf。原始全文留项目资料库，交付权限另行处理。

## 9. 开发任务与验收

| 编号 | 任务与交付物 | 依赖 | 验收 |
|---|---|---|---|
| T01 | OfficeCLI MCP 连通、真实 Word 模板样本 | 无 | 模板内插入文字、公式、表格与图；只改一句后批注/修订仍正确；Word 打开无修复提示 |
| T02 | 项目、文件、版本、作业和本地 Worker | 无 | 上传材料、节点保存、失败续跑；不会重复覆盖已有成果 |
| T03 | 论文/专利题录检索及导入 | T02 | 找回预先已知的相关文献；来源标识、日期、摘要准确；缺失摘要明确 |
| T04 | 知网连接、人工下载接续、授权接口适配点 | T02 | 用户登录并下载一篇可访问文章后，自动入库；过期、无权限和 HTML 伪下载可识别 |
| T05 | 解析与全文精读、技术路线和对照矩阵 | T03/T04 | 随机抽查结论能定位原文；仅摘要项不被伪装成全文结论；CAJ 状态清楚 |
| T06 | 权利要求、说明书和附图生成 | T05 | 一份真实交底形成完整草稿；术语、步骤、图号一致；无虚构实验数值 |
| T07 | 审阅、Word 装配和事务所交付包 | T01/T06 | 正文可编辑、分节与图表正常；工作说明独立；非目标内容不被改写 |
| T08 | 事务所返稿导入、修订和批注回复 | T07 | 保留原修订作者与批注；局部修订可在 Word 接受/拒绝；不自动处理旧修订 |

T01 与 T02 可以并行；T03 与 T04 可以并行；T06 内写作与制图可以并行。同一浏览器 profile 与同一 DOCX 各自串行。先用一件真实项目打通 T01–T07，再扩展平台和并发。

建议前两个工作日先完成 T01 的真实文档试验和 T04 的一篇知网获取试验，同时开始 T02，不把前置检查变成阻止实际实现的阶段。后续工程量在这两个试验之后估算；机构接口获取周期单列，不计为已可控开发工时。

建议目录：backend/app/{api,workflow,agents,connectors,documents,models}、frontend、templates、tests/fixtures、data/projects。上述为未来目录规划，本次未生成应用骨架。

## 10. 来源

- OfficeCLI 官方仓库：https://github.com/iOfficeAI/OfficeCLI
- OfficeCLI 修订：https://github.com/iOfficeAI/OfficeCLI/wiki/word-revision
- OfficeCLI 批注：https://github.com/iOfficeAI/OfficeCLI/wiki/word-comment
- Playwright MCP：https://github.com/microsoft/playwright-mcp
- MCP 传输：https://modelcontextprotocol.io/specification/latest/basic/transports
- MCP 授权安全：https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/authorization/security-considerations.mdx
- 知网会员协议：https://wap.oversea.cnki.net/cn/member/agreement.html
- EPO OPS：https://www.epo.org/en/searching-for-patents/data/web-services/ops
- Semantic Scholar API：https://api.semanticscholar.org/api-docs
- Unpaywall：https://unpaywall.org/api
- Docling：https://github.com/docling-project/docling
- LangGraph：https://docs.langchain.com/oss/python/langgraph/persistence

来源用于能力与边界核查；工具接口、Agent 分工和任务拆解是本项目设计，不代表上述项目原生提供了本规划全部能力。
