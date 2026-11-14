# 2026-11-14 · M3-2b受限PNG简历照片实现候选

## 完成

新增标准库、离线的不可变照片服务：安全basename与显式数据根/profile守卫、5MiB限量原图读取、受限PNG全部压缩行检查、允许元数据清理及原字节绑定。Profile可选登记与脱敏，Material只允许resume主动绑定；无图不读照片。PDF和Word同一PhotoAsset生成，右列完整等比包含；Word新增固定六部件/内部关系/两处统一EMU。照片构建先staged两产物，来源复查后逐文件原子替换、说明最后原子发布。

当前review输出核验读取相同显式档案，匹配全部photo note值，照片DOCX守卫后一次read(8MiB+1)，同一bytes算摘要并核结构。专用EOCD/中央目录前置、六项实际限量解压、CRC/长度/完整压缩流与UTF-8 XML累计节点/深度预算，拒绝隐藏后缀、外链、额外图片、未引用媒体和尺寸篡改。无图输出与历史归档原口径保持。

原作者额度错误后由接替作者独占原worktree/分支继续；基线7287f5c6c192af5847c9708801161c42a3dd4187。13文件接替起点、完整diff和摘要保全在本轮photo/recovery-start；未重造旧证据、reset/clean/stash或访问真实数据。已审定原设计/最终契约按已知SHA原样复制进仓库，仅前置本次集成状态，操作步骤只维护resume-workflow.md第6节，其余规范/入口薄引用。

## 决策

执行经理020选择A与规划者最终CC契约：仅静态8-bit RGB/RGBA非交错PNG，拒绝JPEG/APNG/EXIF/ICC等；不改权限/security_guards、模型、依赖或全局配置。评分摘要排除photo；followup/interview完整Profile摘要不改，登记photo变化仍保守失效。历史投递是当时事实，不跟当前源图一起失效。累计7MiB是附加上限，六单项合法最大合计6,455,296字节，不称存在完整合法7MiB極值包。

## 验证

原作者首次照片19项记录保留（1个Windows symlink因建立能力跳过）；接替首次真实Typst测试暴露新增测试漏导入resume_docx，3子例NameError保留原日志，修复后真实三比例PDF/Word及实际junction/硬链接定向3项全部通过。硬链接结果独立于symlink跳过计数；junction实际建立，profile子路径拒绝、显式选定链接数据根可用。

真实CLI从公开虚构tech-m3档案/材料生成竖RGBA、横RGB、方RGBA三份一页PDF+DOCX；原图/档案/材料前后摘要不变、DOCX媒体等于规范PNG。Windows.Data.Pdf直接渲染最终PDF，作者逐页实看四角颜色、非对称线、比例与alpha、长抬头和正文留白，无重叠或裁切。证据保存在本机协调目录本轮photo/artifacts、pages、page-report.md；属于作者集成检查，不代替独立留出验收。最终三检查在1590份完整源码、27份改动文件冻结后运行：lint_skills与security_guards均退出0；unittest discover共2307项、31项环境跳过，879.975秒，退出0，启用JOBSEARCH_CN_REQUIRE_TYPST=1实际执行真实渲染。测试结束逐文件核对1590份与冻结一致；受检到最终只补本段结果记录，未改产品代码或重跑全量。原始命令/PID/时间/日志及精确差异在本轮photo交付证据。

## 遗留

独立实现审核/留出验收尚未执行。Word/WPS原生页面未验；既有COM 0x80010114与render_docx缺依赖记录继续保留，本轮不重试同法或安装软件。不能用DOCX XML或文本对照宣称原生一页，也没有独立PDF照片像素提取证明。检查后本机并发修改与多文件非事务发布的限制按已审契约明确保留。无真实照片/真实用户材料操作、push或PR。

## 下一步

冻结受检完整文件和最终检查、本地提交后停写，由规划者统一派独立审核与留出验收；按实际可用Word/WPS能力补页面验收。完整照片验收未关闭，真实照片选用仍需用户具体材料任务确认。
