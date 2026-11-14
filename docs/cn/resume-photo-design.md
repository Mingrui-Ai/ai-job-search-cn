# 可选简历照片设计（M3-2b）

> 2026-11-14 集成状态：经理意见书020已选A，受限PNG实现进入送审候选；独立功能验收和Word/WPS原生页面仍待完成。本文以下保留2026-11-11已审定设计原文，历史“未批准/未实现”是当时状态。当前用户步骤只在 [resume-workflow.md 第6节](resume-workflow.md#6-可选简历照片m3-2b)，精确接口见 [resume-photo-contract.md](resume-photo-contract.md)。原设计SHA-256：`51de959f34eac446d597944cf483c96f2adc6a763efaefb6b5670e5c588e9711`。

> 状态：**设计中，待独立复核及规划者裁定**。基线 `38965ead155775f63191ad18e546cc1c482e5eb7`（2026-11-11）。本文没有对应实现；下文带“建议”的字段、参数和行为均为拟议接口。严格 PNG 首片、Word/WPS 一页验收范围尚未得到用户确认，不视为产品承诺。

## 1. 已核实的基础与缺口

| 已有能力及依据 | 对本项的约束 |
| --- | --- |
| [路线图 M3-2b](roadmap.md)已定默认不放、用户决定、照片在 `data/profile/`、PDF/Word 同时支持 | 不从 JD 推导是否放照片，不从现有文件中替用户挑选，不生成或修饰人物照片 |
| [Profile 校验](../../jobsearch_cn/profile.py#L62)拒绝未知键；[默认脱敏](../../jobsearch_cn/profile.py#L263)目前只特别处理 contact | 尚无 photo 字段；新字段必须可选并补脱敏，不能直接加入必填键 |
| [Material 校验与渲染](../../jobsearch_cn/material.py#L148)按引用生成[同一份平铺文字](../../jobsearch_cn/material.py#L448) | 尚无照片选择；不要把图片路径塞进文字内容，[fields_of](../../jobsearch_cn/resume_pdf.py#L198)会把每个字符串都当作应出现在文本层的字段 |
| [score.profile_hash](../../jobsearch_cn/score.py#L70)排除 contact、权重和搜索偏好，其余顶层键均参与摘要 | 新增 photo 若不明确排除，会误使评分过期；现有摘要不能证明照片字节未变 |
| [Typst 编译](../../jobsearch_cn/resume_pdf.py#L108)使用临时根与空包目录，[一页适配](../../jobsearch_cn/resume_pdf.py#L124)在 0.8–1.5 间搜索 | 可把经过校验的本地副本放入该根；不增加网络包或图像依赖 |
| [模板 profile-image 参数](../../jobsearch_cn/resume_templates/habaneraa/lib.typ#L15)等比缩放、绝对放在右上角；[main.typ](../../jobsearch_cn/resume_templates/habaneraa/main.typ#L19)尚未传它 | 当前图片区域**不为文字预留宽度**，不能直接接参数就宣称无重叠 |
| [Word](../../jobsearch_cn/resume_docx.py#L107)只写文本 XML 和 ZIP；[文字对照](../../jobsearch_cn/resume_docx.py#L179)已存在 | 尚无图片部件/关系；[现有说明](resume-pdf.md#word-版)只保证 PDF 一页，没有 Word 分页引擎 |
| [build 生产者](../../jobsearch_cn/cli.py#L846)写材料摘要及输出字节摘要；[build_notes.check_outputs](../../jobsearch_cn/build_notes.py#L96)被 [review validate/show](../../jobsearch_cn/cli.py#L614)共用 | 当前不读当前档案或照片；其注释明确只证实材料/产物一致性，不证明当前事实或版面质量 |
| [store 路径守卫](../../jobsearch_cn/store.py#L304)识别链接、junction/reparse point；[只读输出守卫](../../jobsearch_cn/build_notes.py#L25)逐层检查 | 可复用；现有守卫明确不覆盖检查后被并发换链的竞态，不夸大为敌对本机进程隔离 |

以上为源码/文档核实，**没有实测新照片功能**。本轮未读取真实 data、照片或生成用户材料。

## 2. 建议的用户行为与最小接口

保持现有命令主干，只扩展已有参数与 schema，不另建照片管理系统：

1. **建档**：用户主动提供照片并确认登记时，按 [cn-setup](profile-setup.md)把文件放进 `<data-dir>/profile/`，保存可选 `photo: {"file": "portrait.png"}`；未提供时省略或为 null。不扫描目录、不从简历提取头像、不识别人脸或推断个人属性。更新仍由 cn-setup 负责，cn-resume 不改 Profile。
2. **只读准备**：建议给已有 `profile validate` 增加 `--photo` 参数。它仍先校验档案，再校验登记的图片，并返回不含文件名/路径/元数据正文的安全描述：`binding_hash`、`source_sha256`、`embedded_sha256`、`width_px`、`height_px`、`policy`、`metadata_removed`。缺图或不支持时报错误，不写照片或档案。**此参数尚不存在**；不用 `profile extract` 代替，它只提取 PDF/DOCX 文本。
3. **选择这一份简历放图**：用户明确选择后，Material v1 增加可选 `photo: {"ref": "profile.photo", "binding_hash": "<64位小写SHA-256>"}`，摘要来自上述准备结果。缺失/null 均表示不放；不因 Profile 有照片自动开启，也不增加绕过 Material 的临时 `resume build --photo <任意路径>`。
4. **生成与审核**：沿用 `material validate` → `resume build` → `review draft/validate/show` 与 [共用工作流](resume-workflow.md)的独立审核和两轮规则，均通过同一只读照片校验服务。沟通材料仍拒绝 photo 字段，`material render` 不接受简历。
5. **默认无图**：不读、不校验照片文件、不复制图片、不增加输出图片部件；原有平铺文字、模板无图分支、产物名和生成说明格式保留。Profile 中合法 photo 引用对应的文件丢失，不影响无图简历、匹配或沟通正文；photo 对象本身格式错误仍按 Profile schema 报错。

`profile show` 默认将 photo 的非空值整体隐去（错误形状和未知子键也不回显），不暴露可能含姓名/联系方式的原文件名。新增 flag 的结果只提供安全描述供 Agent 填写材料。旧档案、旧材料不补写 null，不改既有 `material_hash`。

## 3. 建议的字节绑定、失效与审核

**绑定定义**：`source_sha256 = SHA256(有界读取的原文件全部字节)`；`binding_hash = SHA256(规范 JSON {"file": Profile.photo.file, "source_sha256": source_sha256})`。规范 JSON 沿用项目的排序键、紧凑分隔、UTF-8。只绑定登记的相对文件名，不绑定绝对机器路径/mtime；整个数据目录等内容迁移后仍可用。

Material 的 binding_hash 必须等于当前登记名称与原字节的计算结果。Profile 只存一个文件名，不存或自动更新图片摘要；每次明确选图、生成、审核都重新读取。`score.profile_hash` 明确排除顶层 photo（缺失/null/有图均不影响分数摘要）。

照片版 `resume-build` v1 说明建议增加唯一可选 `photo` 对象：`binding_hash`、`source_sha256`、`embedded_sha256`、`width_px`、`height_px`、`policy: "png-v1"`。embedded 摘要是去除允许移除元数据后的规范 PNG **实际字节**。其余 `material_hash`、`profile_hash`、`built_at`、PDF/DOCX 文件名和摘要沿用现有格式。无图说明不加字段；照片材料缺 photo 说明、无图材料配 photo 说明均报错。说明不保存绝对路径、原文件名、元数据内容或原图副本。

| 变化 | 当前照片版的处理 |
| --- | --- |
| 同名文件换字节（包括只改 EXIF/文本元数据）、Profile 指向另一文件 | binding_hash 不同；material validate/build/review draft/validate/show 失败，重新确认选择、更新材料、生成和审核 |
| 删除、改名而未更新 Profile，或改成链接/junction | 来源不可用，当前生成与审核失败；不会自动找同名/相似照片或退回无图 |
| 改名并更新 Profile，像素和原字节未变 | 文件名参与 binding_hash，仍需更新材料和重审；有意采用保守行为 |
| 同一文件同字节，仅 mtime 变化；数据根整体搬家 | 绑定不变，按相同 data-dir/受支持的 profile 路径重新核验后仍有效 |
| 用户改为不放照片，或更换 photo.binding_hash | material_hash 改变，旧审核失效；重新生成无图/新图文件再审 |
| PDF、DOCX、说明或 DOCX 内嵌图片被替换 | 既有完整文件摘要检查 + 新照片检查失败；不靠手改摘要修复 |
| 过去已投递的归档 | 是历史事实；源图变化不删除、不重写归档，不追改历史审核结论 |

**生成的同一输入**：一次读取获得不可变内存快照，检查/清理/哈希均基于它；PDF 临时根里的固定名 `portrait.png` 和 DOCX `word/media/portrait.png` 都来自这同一份 embedded 字节。PDF 编译前后核对临时副本摘要，发布前重新检查当前 Profile 选择和原字节；不同就失败。不会检查一次后让两个渲染器分别重新打开原路径。

**发布失败**：建议照片分支先在受控临时目录生成并检查两份，再逐文件原子替换，最后原子写说明（复用 `_replace`）。现有实现逐个输出，不能声称三文件跨文件系统事务。途中失败或崩溃时不报告成功；旧说明与新文件对不上则审核失败。已有效的旧集合可以保留；若来源已变，它仍不能通过当前照片检查。检查点后的本机并发篡改是现有文件模型限制，核验结论只表示检查当时有效。

**独立审核具体证据**：

- 审核者用同一 data-dir/profile 独立计算当前 binding/source/embedded 摘要，对照 Material 与说明；`review validate/show` 不能再仅检查材料 JSON 和产物，必须对 photo 分支调用该服务。只读，不生成新文件；来源不可用就不展示通过结论。
- DOCX 只接受固定内部图片部件和关系：读取受限 ZIP 项，确认图片恰好一份、`TargetMode` 不是 External、目标为 `media/portrait.png`、部件字节摘要等于 embedded_sha256，绘图关系引用此部件，显示尺寸与等比公式一致。整份 DOCX/PDF 仍核对已记录的 SHA-256。
- **PDF 限制必须写清**：Typst 可能把 PNG 转成 PDF 图像流，不能把 PDF 流字节 SHA-256 冒充原 PNG 摘要。既有工具只有页数/文本/字体检查，没有“提取 PDF 照片并逐像素复核”的接口。首片建议依靠受控副本→编译→输出摘要证明生产链，并将独立 PDF 页面实看作为照片验收项；这不等于脱离生产者的逐像素证明。若要求 CLI 独立证明 PDF 内图像像素与源完全一致，本设计尚不满足，应另行设计有界 PDF 图像检查，不能降低验收口径或引入未批准依赖来掩盖。
- 旧审核与换图：更换来源必须更新 Material 绑定，因此旧审核的 material_hash 不再通过。相同图/相同材料再次 build 沿用当前审核模型：若新版生成物通过说明和图像核验，旧审核格式不强制绑定一次 build 的时间戳。模板/图像策略改变必须重新目检，不能据哈希检查宣称版面重审已完成。

## 4. 建议的路径、格式与元数据边界

**路径**：照片只读 `<data-dir>/profile/<登记文件名>`。文件名是单一 basename（最多 128 字符），拒绝绝对路径、`/`、`\`、`.`/`..`、冒号/ADS、控制字符、尾随点/空格和 Windows 设备名；大小写不自动改写，扩展名按大小写不敏感识别。逐层使用现有 `_is_link`/`_inside` 逻辑，要求普通文件，拒绝 profile 子目录/文件的 symlink、junction/reparse point；建议拒绝可识别的硬链接（`st_nlink > 1`）。数据根本身沿用用户明确选择的根可为链接的规则，照片不得逃出其解析后的 profile 根。

照片版的 `--profile` 只接受该数据根 `profile/` 内的普通档案文件；外部 profile 报明确错误，请用户选对应 data-dir，不从任意 profile 的邻居读图。无图 `--profile` 沿用现状。此限缩只用于新增照片行为。URI/UNC/设备路径不作为照片文件名；不声称可仅靠 pathlib 识别映射网络盘、云同步或用户自行上传，工作流要求使用本机非同步目录。

**首片建议只支持严格静态 PNG**，JPEG 仍明确识别为“不支持”，不丢图继续构建。理由是标准库可以有界检查受限 PNG 的全部压缩像素行；当前项目没有 JPEG 解码器，JPEG 头/尺寸检查不能证明熵编码数据完整。JPEG 后续方案可另评估既有渲染器的保守接入，但不能把解码、方向一致性和元数据清理说成已有能力。

| 项目 | PNG 首片建议策略 |
| --- | --- |
| 文件/像素上限 | 原文件不超过 5 MiB（读取 limit+1 后停）；宽高均为 1–4096，乘积不超过 4,000,000 像素；不靠扩展名和文件 stat 的大小单独判定 |
| 编码 | 签名与 `.png` 一致；只支持 bit depth 8、truecolor RGB/RGBA（type 2/6）、compression/filter method 0、interlace 0。灰度、调色板、16-bit、交错均明确拒绝 |
| 结构与损坏 | 校验各 chunk 长度/CRC、唯一首个 IHDR、连续 IDAT、唯一末尾 IEND、无尾随字节；未知、重复单例块或次序非法 chunk 拒绝。最多 256 chunks，单 chunk 与累计值不能超过文件上限 |
| 解压边界 | 拼接 IDAT，用标准库 zlib 分块/限量解压，预计字节数严格为 `height * (1 + width * channels)`（上述上限下最多 16,004,096）；检查 eof、无多余流/尾随数据、每行 filter 0–4，长度不符/截断/解压炸弹即拒绝。不得先无限 decompress 再比较长度 |
| 元数据清理 | 允许的非像素块 `tEXt/zTXt/iTXt/tIME/pHYs` 在验证长度/CRC 后删除；pHYs 还须为 9 字节、unit 0/1、正数且横纵密度相等，否则拒绝非方形像素/未知比例。不解码/解压文本，不回显键值。可保留合法单个 sRGB 渲染意图字节。重建只含 IHDR、可选 sRGB、合并 IDAT、IEND 的 PNG，保留原 IDAT 压缩字节、重算 CRC，避免不同 zlib 压缩版本改变规范字节。准备结果明确标记是否移除元数据 |
| 色彩/其他块 | iCCP、gAMA、cHRM、tRNS、未知附加块等首片拒绝，不静默移除会改变显示含义的配置；APNG acTL/fcTL/fdAT 拒绝。原图不改写，输出白色页面上保留 PNG alpha |
| EXIF/GPS/方向 | PNG eXIf 一律拒绝，哪怕声称 orientation=1；JPEG/JFIF/Exif 均不进入首片。这样无需不完整的 TIFF/EXIF 解析，不把剥离 EXIF 当旋转。用户须在本机把像素转正并另存为受支持 PNG；工具不自动旋转、裁剪、美化或生成替代图 |

拒绝只返回固定字段路径、错误代码与处理方向，不回显原文件路径、PNG 文本、EXIF/GPS、异常中的二进制内容。成功的原图与规范副本仍是个人数据；清除元数据不等于匿名化或去除像素中可见信息。

## 5. 建议的 PDF/Word 布局与隐私

照片区建议最大 **25 mm × 32 mm**，右侧，和文字间隔 3 mm；`scale = min(25/w, 32/h)`，宽高乘同一比例，完整包含图片、留白、不裁切、不拉伸。最终数值由规划者结合原创夹具可视结果裁定。

- **PDF**：复用 profile-image 概念，但 photo 分支应预留右列与实际 header 高度，正文从两列较高者之后开始，不能沿用无留白的绝对覆盖。仍用现有间距搜索和一页检查；最紧也放不下就停，交用户决定删哪些文字。不缩字号、不删照片凑一页。无图分支原样走旧抬头布局。
- **Word**：标准库新增 PNG content-type、内部关系与 `word/media/portrait.png`，用无边框两列表格和 inline DrawingML 预留空间；尺寸用相同物理单位转 EMU，锁定比例，不用外链、浮动叠图或文件名作为 alt text。文字仍来自同一平铺内容，沿用全文对照。
- **一页验收边界**：PDF 可机器硬拒绝多页；DOCX 没有分页引擎，不能以 `docProps` 页数或 XML 猜测替代实看。首片建议要求明确版本的 Word 和 WPS 各打开原创验收样本，确认一页、无重叠、图像方向正确、比例正确。对任意阅读器/字体的自动一页保证仍做不到。真实文件若 Word 多页则停在交付检查，由用户决定删内容再按流程生成/重审；不能把这项描述成 CLI 已保证。
- **本地隐私**：原图、规范副本、PDF/DOCX、说明及投递归档都留在用户本机 data 范围；无上传、联网转换、外部图片 URL 或模型图像调用。临时副本使用现有 TemporaryDirectory 生命周期，异常也清理；不许宣传为安全擦除，异常中断/系统备份的副本只能按本机数据策略处理。
- **页面审核**：原创夹具可供独立 Agent 看页面；真实含照片 PDF 若页面工具会上传给模型/外部服务，不调用该工具。本机用户打开 PDF/Word/WPS 完成目检，交付明确标记 Agent 未目检的项目。字节检查不推断照片是谁、是否合适或个人属性。若用户以后要求远程视觉审核，应另行确认数据边界，不自动扩大本项授权。
- **公开范围**：只提交代码、规则、原创几何色块夹具、匿名验收期望。测试不得用用户照片或 AI 人像；不提交真实文件名、联系信息或导出文件。默认 data 已忽略；自选 data-dir 也必须置于非跟踪的本机目录，不能据默认 `.gitignore` 宣称任意目录均安全。

## 6. 精确影响面与兼容策略（拟议）

| 文件/接口 | 拟议改动与消费者 |
| --- | --- |
| `jobsearch_cn/profile.py`，`score.py` | photo 可选结构、脱敏；评分摘要排除 photo。现有 match/material 的非照片语义保留 |
| **新增** `jobsearch_cn/resume_photo.py` | 单一有界只读校验/清理/绑定服务，返回不可变照片值；重查和 DOCX 图片核验复用它，不写 Profile、不联网 |
| `jobsearch_cn/material.py` | 仅 resume 接受可选 photo 对象与固定 ref/hash；保持 render 的纯文字返回值 |
| `jobsearch_cn/cli.py` | `profile validate --photo`、`_check_material`、resume build、review draft/validate/show 接同一服务；照片参数作为独立内部值传给 PDF/Word；扩展 build_note 生产；照片错误安全输出 |
| `jobsearch_cn/resume_pdf.py`，`resume_docx.py` | 可选 keyword-only photo 输入；临时图复制、预留布局、DOCX 图片部件、照片分支 staged build；原调用不传 photo 时兼容 |
| `jobsearch_cn/resume_templates/habaneraa/main.typ`、`lib.typ`、`SOURCE.md` | 条件照片抬头；无图分支保持；记录第三方模板的最小改动与原 MIT 来源 |
| `jobsearch_cn/build_notes.py` | v1 note 可选 photo 严格校验；check_outputs 照片分支读当前来源并核验 DOCX 真实部件/尺寸，继续验证完整 PDF/DOCX 摘要 |
| `jobsearch_cn/review.py` | 现有 material_hash 已含新增 photo，原则上不改审核 schema；只在实现发现固定字段白名单需要时最小调整并报告 |
| `jobsearch_cn/applications.py` | 历史归档 `read_note/_check_note` 只消费原有 files/material_hash，建议不改数据库/事件/schema，不要求旧源图仍在，不扩展归档为单独原图 |
| `jobsearch_cn/followups.py`、`interview.py` | **已知间接影响**：当前分别对完整 Profile 作摘要（[followups](../../jobsearch_cn/followups.py#L172)、[interview](../../jobsearch_cn/interview.py#L179)）。新增/改 photo 字段会保守使现有上下文过期；首片不改这两个完整摘要契约，原文件字节变化但 Profile 未变则与它们无关。此影响须在发布说明告知 |
| `docs/cn/profile.md`、`profile-setup.md`、`material.md`、`resume-pdf.md`、`resume-workflow.md`、`review-format.md`、`review-checklist.md`、`applications.md` | 只在各自唯一规范处描述字段、选择/失败/审核与生成说明；D5 补照片版目检和未目检状态；applications 只补共享说明，不更改历史记录流程 |
| `tests/test_cn_profile.py`、`test_cn_material.py`、`test_cn_resume_build.py`、`test_cn_resume_pdf.py`、`test_cn_resume_docx.py`、`test_cn_review.py`，新增 `test_cn_resume_photo.py` 与原创夹具目录 | 按下表覆盖新行为；照片真实 Typst 渲染用例放进现有 `test_cn_resume_pdf.py`，由现有 CN 渲染 CI 执行，无需新增下载/依赖 |
| `tests/test_cn_score.py`、`test_cn_applications.py`、`test_cn_followups.py`、`test_cn_interview.py`、`test_cn_package.py` | 分数摘要、历史归档、完整 Profile 消费者兼容；核对新模块标准库/离线守卫覆盖，不改守卫边界 |
| `AGENTS.md`、`.claude/skills/cn-resume/SKILL.md`、`.dsh/skills/cn-resume/SKILL.md`、`.claude/skills/cn-setup/SKILL.md` | 现有薄指针已覆盖共用流程，原则上不改。若触发词确需补“照片”，再单独列最小 diff |

`.claude/settings.json` 与 `tools/security_guards.py` 现有 `profile/material/resume/review:*` 权限已覆盖上述命令族（[依据](../../tools/security_guards.py#L108)）；**本设计不修改这两处，不新增权限/依赖**。若后续选独立转换器、Word 自动化或额外读写范围，应先把具体变更交规划者，按仓库规则决定是否需经理意见书；广义命令匹配不等于此类新行为已获授权。

旧数据兼容目标是旧 JSON/哈希/命令形状/文字和版式不变；PDF 时间信息与 DOCX ZIP 时间可能变化，不能把跨次输出的整个二进制相等当作已有保证。旧运行时不能识别 photo 字段时明确报错，不要求它静默降级。新版保留无图旧说明，照片版才要求新增 photo 说明。

## 7. 独立验收矩阵（实现后执行，当前均未执行）

| 编号 | 独立输入/动作 | 必须观察到的结果 |
| --- | --- | --- |
| C1 | 旧 Profile/Material/旧 build_note，summary 有/无，各方向已有合成样例 | 无迁移可用；原哈希、平铺内容、版式与文本对照兼容；不读照片文件，无 media 部件 |
| C2 | Profile 登记图片但 Material 缺失/null photo；登记文件缺失/为不支持图片 | 无图行为照旧；不自动加图或报图片文件错误；不为测试改变旧冻结期望 |
| B1 | 明确选图、source/name/binding/embedded 独立计算；PDF/Word 成功生成 | 材料/说明与原字节绑定；DOCX 实际 media 字节一致；两份文本一致，一页/比例/位置按 L1 验收 |
| B2 | 同路径同 mtime 替换字节、只改文字元数据、Profile 改文件名/换图、删除图 | validate/build/review 各入口结论一致且非零；原审核无法继续通过，不生成无图替代 |
| B3 | 修改 mtime；整个 data 根等内容搬家；去掉 Material.photo | 前两者核验仍有效；去图使旧 material_hash 审核失效，重新生成后无图 |
| B4 | 单改 PDF/DOCX/media/关系/说明，缺 photo note，照片材料配旧 note | 当前审核拒绝；含 External 关系或假 media 不得通过“存在图片”检查 |
| P1 | `../`、绝对/UNC、ADS、设备名、尾点空格、子目录、扩展名伪装 | 安全错误，不读取根外数据；错误和日志无原名/元数据正文 |
| P2 | 照片/profile 目录链接、Windows junction/reparse point、硬链接；根为用户选定链接 | 子路径拒绝，根按明确规则可用；不把未能建立的 Windows 夹具标通过 |
| F1 | 原创 RGB/RGBA 色块、横/竖/方、透明边缘；允许文本/DPI 块 | 清理后像素数据一致，embedded 摘要可复算；输出无文字/DPI元数据，未改原图 |
| F2 | CRC错、截断、重复块、尾随流、错误filter、超尺寸/超像素/超文件、解压炸弹 | 有界终止且明确错误，不发布有效说明；边界恰好值按规定接受 |
| F3 | JPEG、伪PNG、APNG、16-bit、调色板、交错、EXIF/GPS、ICC/未知块 | 逐类明确拒绝，无静默旋转/降级/联网转换 |
| L1 | 原创四角不同色/非对称几何夹具，长抬头、长意向、近一页极限文本 | PDF 真编译一页；Word及WPS记录版本实看一页；无叠字/裁切/畸变/方向反转；PDF实际可见图对应夹具，不能只看DOCX XML |
| L2 | 最紧 PDF 仍多页；Word 实看多页；缺字体/Typst/本机查看能力 | PDF生成失败；Word/页面未验明确标未通过交付验收，不伪报一页或静默丢图 |
| A1 | 照片部件写失败、DOCX失败、说明写失败、编译超时、过程中源图替换 | 无成功报告；新集合不成为有效当前审核，旧文件可保留且状态准确；临时副本正常异常退出均清理 |
| R1 | 图片Profile字段新增/改名；已记录投递归档、followup/interview上下文 | 评分摘要不变；历史归档仍按当时字节有效；完整Profile上下文按现有契约过期，原因和影响可解释 |
| S1 | stdout/stderr、repo status、DOCX zip、PDF元数据与本地临时目录检查 | 不公开真实原图/原名/EXIF/联系方式；公开夹具仅原创几何图；DOCX无外部关系；个人导出留本地 |

没有真实 Word/WPS 实看或 PDF 照片目检时，工程部分可报告结果，**不能勾选照片完整验收**。独立验证者先冻结原创输入与预期；实现者不以自测代替独立验收。代码提交仍须仓库三检查及现有真实渲染 CI。

## 8. 一次完整交付的切法与待裁定

建议一个实现单元同时交付：严格 PNG + Profile 登记/只读准备 + Material 选择/绑定 + PDF/DOCX 嵌图 + 当前审核来源/部件核验 + 共用流程 + 上表验收；不要先合入“能嵌图但换图后旧审核仍通过”的半成品。实现完成前先有独立设计审查，当前工作止于本地文档。

需规划者在设计审核后确认、必要时形成经理意见书：

| 待决 | 推荐与代价 | 备选及新增工作 |
| --- | --- | --- |
| 首片格式范围 | 严格 PNG，JPEG/EXIF明确拒绝；部分现成照片需用户本地另存 | 同时做 JPEG：另设计完整损坏检测、元数据清理、EXIF方向/色彩处理与PDF/Word一致性；不能靠扩展名或头部检查过关 |
| 一页承诺 | PDF机器保证；明确版本 Word/WPS 原创样本实看 + 真实文件用户本机确认 | CLI对任意Word强保证目前不可行；若增本机Office/WPS分页验证，需另查调用/授权与失败语义 |
| PDF 独立图像证明 | 同源不可变字节生产链、产物SHA、独立页面实看；明确不是独立逐像素证据 | 新增有界PDF图像解析/既有可用工具核验方案，先证明能在现有依赖范围实现，再升级承诺 |
| 照片版外部 --profile | 限于指定 data 根的 profile 目录，便于默认无图兼容和统一读图边界 | 若需任意外部 profile 根，单独定义用户选根、链接与隐私规则，不能自然继承任意邻居文件读取 |

没有需要本轮变更权限或不可逆操作的步骤；这些尚未确认的取舍保持“建议”，不替用户作结论。
