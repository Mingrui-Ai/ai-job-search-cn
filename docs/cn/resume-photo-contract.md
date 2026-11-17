# 可选简历照片：接口补充（M3-2b，P3-1/P3-2）

> 2026-11-14 集成状态：经理020已选受限PNG方案A，接口已接入当前送审候选。以下保留已独立审定的最终契约原文和当时状态；当前流程见 [resume-workflow.md 第6节](resume-workflow.md#6-可选简历照片m3-2b)。原契约SHA-256：`65a1c61d2cd1c94ffedf4ac287e3b68ba1b05f0432ac39575ac4cacbc6a59da5`。机器测试、作者PDF实看与独立/Word/WPS验收分开记录，不因实现候选而关闭完整验收。

> 仅补[冻结设计](resume-photo-design.md)的两项 P3，基线 `38965ead155775f63191ad18e546cc1c482e5eb7`，主设计 SHA-256 `51de959f34eac446d597944cf483c96f2adc6a763efaefb6b5670e5c588e9711`。**下列接口均未实现，D1 格式范围仍待经理意见书 020 决定，不据此开工。** 本表以原严格 PNG 建议为前提；若经理选择不同范围，再补契约，不暗改原冻结稿。

规划者已裁定的 D2–D4 原样保留：PDF 机器一页，Word/WPS 记录实际可用版本并实看；同源图片副本、产物摘要、DOCX 实际部件核对和独立 PDF 页面实看，不新增 PDF 像素解析器；照片版档案限于所选 data 根的 profile 目录，无图外部 `--profile` 行为保留。本文不新增命令族、权限、依赖或图片管理流程。

## 1. P3-1：值与服务契约

当前 [Profile](../../jobsearch_cn/profile.py#L62) 与 [Material](../../jobsearch_cn/material.py#L148) 使用严格键校验，[build note](../../jobsearch_cn/build_notes.py#L50)也有固定字段。建议可选 photo 只按下表扩展，`schema_version` 仍为 1；旧对象不自动补键。

| 对象 | photo 精确形状 | 缺失/null 与拒绝规则 |
| --- | --- | --- |
| Profile | `{"file": str}`，恰好一个键；file 为主设计 §4 规定的安全 basename | 缺失或 null＝未登记；空串、数组、bool、数字、额外键（包括 policy）拒绝。此层只查结构，不读图；不因图片丢失阻断无图行为 |
| Material，kind=resume | `{"ref": "profile.photo", "binding_hash": Hash}`，恰好两个键 | 缺失或 null＝不放；非空对象才进入照片服务。ref 不接受其他路径，空对象/额外键拒绝；其他 kind 连 photo:null 也不接受 |
| resume-build note | `{"binding_hash": Hash, "source_sha256": Hash, "embedded_sha256": Hash, "width_px": Int, "height_px": Int, "policy": "png-v1"}`，恰好六个键 | 无图必须省略 photo，null 不合法；照片材料必须有完整对象。message-build 不接受 photo。未知键、未知 policy 拒绝，不按“最新版”猜测 |
| `profile validate --photo` 成功时的 photo 描述 | 上一行六键加 `"metadata_removed": Bool`，恰好七键 | 只读准备成功才给对象；校验失败（退出1）给 photo:null，沿用 valid/errors/warnings 外壳；档案输入不可读（退出2）沿用输入错误外壳，不产生 photo 描述。不带 flag 时不加 photo 输出键，不检查照片 |

`Hash` 必须为长度 64 的小写十六进制字符串，全文匹配 `[0-9a-f]{64}`，不接受尾部换行、大小写自动转换或非字符串。`Int` 是 `type(value) is int`，拒绝 bool；宽高各 1–4096，乘积 ≤4,000,000。`Bool` 仅 true/false，不接收 0/1。先完成类型检查再比较范围。上述尺寸和 PNG 上限继承主设计，不是新增产品选择。

`binding_hash` 严格沿用主设计：对 `{"file": 原登记basename, "source_sha256": SHA256(原文件全部字节)}` 做键排序、紧凑分隔、UTF-8 JSON 的 SHA-256；不放绝对路径、档案文件名、mtime。只有 photo.file 相对图片名参与绑定；同根内不同档案恰好登记同一图片时可以有同一绑定。note 六项必须与当前只读值逐项相等，不能只比较 binding_hash 后相信其中任意尺寸或 embedded 摘要。

**内部只读值（拟议名 `PhotoAsset`）**：冻结记录，字段为上述七项，加 `asset_name: Literal["portrait.png"]`、`embedded_bytes: bytes`。所有字段为不可变标量/bytes，不接受 bytearray、文件句柄或任意 Path；构造时保证 `SHA256(embedded_bytes) == embedded_sha256`、PNG 尺寸相符及既定清理策略已完成。原图字节只在准备期间有界持有，不交给渲染器。打印时只能投影七项描述，不能序列化 bytes/base64/源路径。

| 拟议内部接口 | 输入、输出和调用责任 |
| --- | --- |
| `prepare_photo(root, profile_path, profile_data) -> PhotoAsset` | 三项都显式传入；profile_data 是调用者从该 profile_path 刚读并校验的快照。检查照片版 root/profile 边界和 photo 结构，按所登记 basename 有界读图、清理、计算绑定。返回值不携带路径；不写入任何文件 |
| `require_photo_binding(selection, asset) -> None` | selection 是 Material.photo；按固定 ref 和 binding_hash 检查。结构/绑定不符均失败；不改 Material，也不替它填当前摘要 |
| `recheck_photo(root, profile_path, expected_asset) -> None` | 从同一显式 profile_path 重新读取并校验当前档案，再调用同一 prepare 逻辑；比较全部六项 note 值及 embedded bytes。发布前及只读产物核对结束后调用。来源变化/不可用失败，不更新 expected_asset |
| `check_docx_photo(container_bytes: bytes, asset) -> list[str]` | 只接受不可变 bytes，不接受 Path、bytearray 或文件句柄，不打开文件；先对 bytes 检查8 MiB上限，再按 §3–4 核验 EOCD、ZIP/XML、图片、关系和尺寸。返回安全字段路径+固定原因，不回显 XML、路径或图片内容 |
| `build_notes.check_outputs(root, material_file, material, declared_name, *, profile_path=None) -> list[str]` | 保留原四位置参数和返回值。无图分支不读取 profile_path；照片分支显式选档案→prepare→require binding→核对 note。照片 DOCX 通过路径守卫后一次限量读取，完整摘要比对和 check_docx_photo 消费同一 bytes，随后按原口径 recheck；具体顺序见§4。库函数不猜默认档案 |
| PDF/Word 生成器新增 keyword-only `photo: PhotoAsset | None = None` | `resume_pdf.render`、`resume_docx.build/write` 接收相同 asset；只消费固定 asset_name、embedded_bytes、尺寸和策略，不打开原图/档案。原位置参数不改；`material.render` 仍只返回文字 content，图片不进入 fields_of |

接口名可以随实现习惯调整，但表中参数显式性、只读责任与默认分支不能改变。统一照片错误使用固定 code/字段（如 `photo.binding_mismatch`、`photo.source_unavailable`、`photo.profile_outside_root`、`photo.invalid_type`、`photo.unsupported_policy`），不包含用户值。CLI 将照片结构/来源/预算错误映射为退出 1；显式档案输入读不了/不是 JSON 沿用退出 2，照片分支用安全错误描述。现有各命令 stdout/stderr 外壳不另造一套；无图错误和命令行为不变。

## 2. P3-1：替代档案必须贯穿命令

已核实 [profile 的位置参数](../../jobsearch_cn/cli.py#L226)、[审核 --profile 参数](../../jobsearch_cn/cli.py#L1661)均存在；缺口是 [_checked_review](../../jobsearch_cn/cli.py#L614)目前普通简历只调用四参数 check_outputs，help 也只说 followup。不是新增审核参数。

| 命令/层 | 档案选择和传递 |
| --- | --- |
| `profile validate [file] --photo --data-dir D`（--photo 拟议） | 用现有位置参数 file；省略才用 `D/profile/profile.json`。传实际选中的 Path 和由它读出的 data 到 prepare；照片允许 `D/profile/alternate.json`。不改变原无图 sources/notes 查找语义 |
| `material validate`、`resume build`、`review draft` | 先按现有 `--profile` 选择档案；省略才用同一 D 的默认档案。照片检查传同一 Path/data；build 保存 prepare 的同一 asset 给两个生成器，并用同一 Path recheck |
| `review validate/show` | `_checked_review` 对照片材料在 CLI 边界解析 `--profile`，将该 Path 显式交给扩展的 check_outputs；没有 --profile 才传 D 的默认 Path。不根据审核文件、说明或材料位置推断档案 |
| 显式档案不存在/越界/失效 | 报错，不退回默认档案。D4 越界限制仅用于照片分支；无图外部 --profile 保持已有行为，普通无图 review 也不新增档案读取 |

建议 `profile validate --photo` help：“只读检查登记的简历照片并输出安全绑定描述；档案沿用位置参数，照片与档案须位于本次数据目录的 profile/ 下；不写文件。”审核 `--profile` help 改为：“followup 或含照片简历核对当前档案；省略用本次数据目录的 profile/profile.json；生成与审核须传同一档案，含照片时限于该目录。”不宣称 `--photo` 已存在。

**正例（实现后执行）**：原创数据根 D 中默认档案登记 default.png，`profile/alternate.json` 登记不同的 alt.png。先用下列第一行准备，用户明确选图后由其 binding_hash 写 Material M，再贯穿其余命令；R 是按原独立审核流程创建的审核文件。所有行均指向相同 D/alternate；须记录服务实际收到的 Path 并核对 alt 图片字节，不能仅断言退出码。

```text
python -m jobsearch_cn profile validate "<D>/profile/alternate.json" --photo --data-dir "<D>"
python -m jobsearch_cn material validate "<M>" --profile "<D>/profile/alternate.json" --data-dir "<D>"
python -m jobsearch_cn resume build "<M>" --profile "<D>/profile/alternate.json" --data-dir "<D>"
python -m jobsearch_cn review draft "<M>" --profile "<D>/profile/alternate.json" --data-dir "<D>"
python -m jobsearch_cn review validate "<R>" --profile "<D>/profile/alternate.json" --data-dir "<D>"
python -m jobsearch_cn review show "<R>" --profile "<D>/profile/alternate.json" --data-dir "<D>"
```

**反例**：对 alt 材料/审核，分别显式给 default 档案或省略 --profile，必须因绑定不同失败且不展示通过结论；显式给不存在的 alternate 路径，必须报输入不可读而不是成功使用 default。另以无图旧材料+外部档案复查旧行为；不得让新边界扩散到无图分支。

## 3. P3-2：DOCX 图片结构与统一尺寸

基线 [resume_docx.py](../../jobsearch_cn/resume_docx.py#L32)只定义 w 命名空间与 styles 关系，[build](../../jobsearch_cn/resume_docx.py#L122)只写五个部件。下面六部件/关系表仅适用于新增照片分支；无图仍为原五部件。URI 是固定 OOXML 标识，不是网络读取来源。

| 部分 | 生成与核验的精确契约 |
| --- | --- |
| ZIP 部件集合 | 恰好 `[Content_Types].xml`、`_rels/.rels`、`word/document.xml`、`word/styles.xml`、`word/_rels/document.xml.rels`、`word/media/portrait.png`；没有目录条目、其他 media、thumbnail、附件或宏 |
| content types | 保留现有 rels/xml Default 和 document/styles Override；新增且仅一项 `Default Extension="png" ContentType="image/png"`。不重复声明、无其他 Override；图片字节须通过同一受限 PNG 校验且摘要等于 asset |
| 包关系 `_rels/.rels` | 沿用唯一 `rId1`，Type=`http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument`，Target=`word/document.xml` |
| 文档关系 `word/_rels/document.xml.rels` | 恰好两项：现有 `rId1` styles，Type=`http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles`，Target=`styles.xml`；新增 `rId2` image，Type=`http://schemas.openxmlformats.org/officeDocument/2006/relationships/image`，Target=`media/portrait.png`。ID 在各自关系部件内唯一，包关系的 rId1 不冲突 |
| 关系限制 | 生产者省略 TargetMode；核验仅接受缺失或 `Internal`。External、其他值、额外/重复关系、不同 ID/Type/Target、URL、绝对路径、反斜杠、别名/转义路径均拒绝，不 resolve/fetch 声明的目标 |
| DrawingML | 全文恰好一个 `w:drawing/wp:inline`，无 `wp:anchor`；其 `a:graphic/a:graphicData` 的 uri 固定为下表 pic URI，内部恰好一个 `pic:pic`，`pic:blipFill/a:blip@r:embed="rId2"`，无 r:link、其他 blip 或裁剪 srcRect |
| 几何 | `wp:extent@cx/@cy` 与 `pic:spPr/a:xfrm/a:ext@cx/@cy` 都等于统一函数输出；`a:xfrm/a:off` 为 x=y=0，不旋转/翻转；`a:prstGeom@prst="rect"`；`a:stretch/a:fillRect` 显示完整图片；框架/图片 noChangeAspect=1 |
| 安全属性 | `wp:inline` 四边 dist=0；`wp:docPr id="1" name="Resume photo" descr="Resume photo"`，`pic:cNvPr id="0" name="Resume photo"`；不写源文件名、姓名、EXIF或其他用户值到 name/descr/title。两个 id 作用域不同；全文不可出现第二份绘图/重复 docPr id |

| 前缀 | 固定 namespace URI |
| --- | --- |
| w | `http://schemas.openxmlformats.org/wordprocessingml/2006/main` |
| r | `http://schemas.openxmlformats.org/officeDocument/2006/relationships` |
| wp | `http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing` |
| a | `http://schemas.openxmlformats.org/drawingml/2006/main` |
| pic | `http://schemas.openxmlformats.org/drawingml/2006/picture` |
| OPC relationships / content types | `http://schemas.openxmlformats.org/package/2006/relationships` / `http://schemas.openxmlformats.org/package/2006/content-types` |

核验按 namespace URI + local name 判断，不以 XML 前缀拼写作为身份；生产者统一用表中前缀。对应的 aspect lock 位置为 `wp:cNvGraphicFramePr/a:graphicFrameLocks` 和 `pic:nvPicPr/pic:cNvPicPr/a:picLocks`。要求同一图片关系实际被绘图引用；仅存在 media 文件不算嵌图成功。

**统一 EMU 计算（生产者与核验者共用）**：1 mm=36,000 EMU，1 twip=635 EMU；继承主设计初始上限 W=900,000（25 mm）、H=1,152,000（32 mm），不是已经目检适合所有内容的数值。定义正整数半入舍入 `R(n,d) = (2*n+d)//(2*d)`，不用 float 或 Python round。若 `W*h <= H*w`，输出 `(cx,cy)=(W,R(W*h,w))`；否则输出 `(R(H*w,h),H)`。两处尺寸须为规范十进制正整数且精确等于计算值，拒绝符号、小数、指数写法和近似容差。只允许舍入造成的半个 EMU 以内误差，不拿严格浮点宽高比误判。

| 原图 w×h | 应有 cx×cy（EMU） | 目的 |
| --- | --- | --- |
| 400×600 | 768000×1152000 | 竖图按高度约束 |
| 800×400 | 900000×450000 | 横图按宽度约束 |
| 3×7 | 493714×1152000 | 非整除的有理数舍入 |
| 64×1 | 900000×14063 | 14062.5 半入，不能用银行家舍入变为14062 |

右列若按 twip 分配，至少 `ceil((900000+108000)/635)=1588` twips，含 3 mm 间隔；间隔本身用同一 R 转为 170 twips。先向上预留列宽，再放已计算的 inline 尺寸，不把列宽反算成图片尺寸。未知尺寸或超过主设计范围先拒绝，不能除零或自动裁切。

## 4. P3-2：受限 ZIP/XML 读取及验收例

现有 [resume_extract](../../jobsearch_cn/resume_extract.py#L27)已经使用文件/XML/节点/深度上限，且[读取 limit+1 防伪造 file_size](../../jobsearch_cn/resume_extract.py#L127)。新增照片核验对象是自家固定六部件简历，建议用更小的专用预算；不改变通用简历提取器，也不放宽其上限。

**照片 DOCX 的唯一读取顺序**：check_outputs 完成该路径的现有守卫后，打开一次，以 `read(8 * 1024 * 1024 + 1)` 获得不可变完整容器 bytes；超过8 MiB立即失败。用此 bytes 计算 SHA-256 并比对 note.files 中该DOCX的预期摘要；匹配后把同一 bytes 传给 check_docx_photo，结构函数再检查长度并以 BytesIO 解析，不能重开路径。该分支必须跳过现有 `path.read_bytes()`，不能先无界读取再限量，也不能让摘要与结构各自读取一次。无图 DOCX、PDF 完整摘要、历史归档与来源 recheck 保持原口径；这里只保证当次两种核验的输入相同，不阻止读取期间或检查结束后的外部修改。

| 预算/检查 | 精确建议与理由 |
| --- | --- |
| 容器 | check_outputs 按上述顺序一次最多读8 MiB+1；check_docx_photo 对收到的同一 bytes 再检查≤8 MiB。先看无注释 EOCD，单磁盘、恰好6项、central directory ≤16 KiB且区间在 bytes 内；拒绝 ZIP64、多卷、注释及尾随字节，再以 BytesIO 交标准库 ZipFile。固定6项无需通用大ZIP能力 |
| 项名/压缩 | infolist 恰好固定六个区分大小写的名称；在按名字读取前检查重复名称，任何多余项/目录/别名即拒绝。只接收 ZIP_STORED/ZIP_DEFLATED，拒绝加密、entry comment/extra；不解压到文件系统 |
| 单项实际解压字节 | portrait.png ≤5 MiB；document.xml ≤1 MiB；styles.xml ≤64 KiB；另三项 XML 各≤32 KiB；所有项累计≤7 MiB。图片限额继承主设计，其余远大于固定模板与一页文字正常用量，仍小于通用提取器16 MiB XML上限；实现验收超限须报告，不自动加大 |
| 读法 | 先检查 ZipInfo 声明预算，再按≤64 KiB块读取，每项最多预算+1并累计；CRC/实际长度不符、解压异常立即拒绝。ZipInfo 和压缩比不作为实际解压大小的唯一证据 |
| XML | 只解析上述五个XML部件，严格 UTF-8（声明若有，只允许UTF-8）、禁止NUL/DOCTYPE/ENTITY，累计节点≤50,000、深度≤64；用受限 iterparse start/end计数，超限停。每个文档根、关系和图片节点按§3检查；不解析XML指向的外部对象 |
| 输出 | 核验只返回固定问题字段/原因，不吐 XML、文件名清单或异常二进制。检查完重核当前来源；不生成“修复过的Word”，也不修改产物/说明 |

这些是**待实现预算**，不是已有运行统计。容器前置 EOCD 限制用于防止 ZipFile 先接受大量中央目录条目；条目上限不能只在任意大目录解析完后才检查。EOCD/目录/各条目区间矛盾、重叠条目或坏本地头按 BadZip/安全错误拒绝，不扫描归档寻找替代部件。

累计7 MiB是附加上限：六项各自上限相加仅6,455,296字节，小于7,340,032字节，因此所有单项合法时达不到累计边界。若单独验证累计计数层的“7 MiB接受/+1拒绝”，须明示只测计数层，并以人工计数输入隔离其他约束；不得将违反单项上限的包称为完整合法极值。其他边界也只在被测层前提满足时构造，恰好一个上限不等于整包合法。

| 验收例（实现后执行） | 应观察到的结果 |
| --- | --- |
| 每种 photo 对象注入未知键、宽高 true/1.0/"1"、大写/带换行Hash、未知policy；note photo:null | 所有相关入口给相同结构结论；不升级/填值/无图回退；旧缺失/null Material仍不读照片 |
| §2 alternate 正反例 | 正例全链路读取alternate并嵌alt字节；反例绑定失败或输入不可读，show不显示通过；无图外部档案行为不变 |
| 正常六部件，rId1 styles+rId2 image；§3四组尺寸 | media摘要、PNG尺寸、实际r:embed与两处EMU都匹配；样式关系仍可用；文本仍通过原对照 |
| media相同但drawing未引用、rId2重复/改External、多余image关系/图片、r:link、篡改一处extent | 均拒绝；不能仅凭产物里找到相同PNG字节判通过 |
| 照片DOCX读取 trap：令该路径的 read_bytes 或无 size 的 read 立即失败，记录 open/read 次数与 size；构造限量读取超限 | 正常分支只打开一次、读取参数为8 MiB+1；超限在摘要/结构核验前失败。PDF和无图DOCX的原路径不纳入此trap，不能用旧无界读取后再检查长度蒙混通过 |
| 受控路径替换：先读取完整容器A，摘要比对后/结构核验前把路径换成不同容器B | 摘要输入与结构实参必须都是捕获的A bytes；结构函数不得重开路径读B。A满足预期时当次核验可通过，但不能声称当前路径仍是A或阻止了外部修改 |
| 重复ZIP名称、大小写/斜杠别名、未知压缩/加密、伪造file_size、CRC错、炸弹、XML深度/节点/DTD、EOCD条目过量 | 有界失败且不解压到文件系统/取外链。恰值/+1案例按被测层前提构造，累计层按上段单独验证，不宣称存在单项全合法的7 MiB极值包；不改真实图片或扩大预算 |
| XML和字节通过但Word/PDF实看未做 | 只报告机器核验；D2/D3页面验收仍未完成，不宣称一页或图片目检通过 |

本补充不运行上述例子，不报告功能通过数。接下来由原未参与设计的审核者增量检查；原冻结设计/工作记录/路线图与经理意见均不覆盖。

2026-11-11 本次增补仅落实照片 DOCX 的单次限量 bytes 输入和累计预算措辞；P3-1 已由规划者接受，P3-2 本次变化仍待增量复核。修改前两份接口补充文档已在本轮协调目录按原字节保全，不覆盖旧交付或审核证据；020仍未批准。
