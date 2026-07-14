# 安全威胁模型

本模型针对本地/单实例、小团队 Beta：浏览器和 API 属于受控应用，上传文件、URL 内容、请求参数及可选外部 provider 均按不可信输入处理。它记录已实现控制和剩余风险，不把“本地运行”当成安全保证。

![Browser、API、不可信输入、外部 provider 与存储之间的信任边界](assets/security-boundaries.svg)

## 资产与目标

需要保护的资产包括：原始文档、解析文本、问题/回答历史、反馈快照、API 凭据、provider 请求、操作日志、向量和对象存储引用。安全目标是防止未授权读取/修改、服务资源耗尽、内网探测、路径越界、敏感信息进入日志，以及低可信证据被包装成事实。

## 信任边界

| 边界 | 进入的数据 | 当前控制 | 仍需部署方承担 |
| --- | --- | --- | --- |
| Browser → Nginx/API | 参数、文件、认证头 | schema、上传限制、可选 bearer、request ID、限流 | TLS、OIDC/SSO、CSRF/CSP 策略、边缘 WAF |
| URL → fetcher | 地址、重定向、DNS、响应 | HTTP(S) only、禁凭据、逐跳 SSRF 校验、类型/大小/超时 | 出站代理、DNS pinning 策略、网络 egress allowlist |
| 文件 → parser/OCR | 文件名、bytes、解析器输出 | 扩展名、大小、空文件、magic bytes、DOCX 条目/展开体积/压缩比、唯一落盘名、失败清理 | 沙箱解析、AV/CDR 与复杂格式隔离 |
| API → provider | 文本、embedding/answer 请求 | 默认禁用、显式配置、超时、production fail-closed、`store:false`、错误脱敏 | 数据处理协议、区域/保留策略、密钥轮换、配额 |
| API → local storage | 文档、历史、反馈、日志 | 受控路径、SQLite registry、删除路径约束 | 磁盘加密、备份、保留/彻删、workspace 授权 |
| Runtime → observability | 异常与 trace | 可选 Sentry、默认关闭 PII/body、日志字段脱敏 | 项目访问控制、采样、告警、审计和删除策略 |

## 主要威胁与处理

### 恶意上传

风险包括伪装扩展名、超大文件、ZIP bomb、路径穿越、解析器漏洞和上传残留。当前实现按块读取并限制 20 MB，拒绝空文件和不支持扩展名，对 PDF/PNG/JPEG 校验签名；DOCX 验证 Office 结构、条目数、展开体积和压缩比；使用随机前缀与 basename 落盘，失败时删除暂存文件。纯文本/Markdown 无可靠 magic bytes，仍按不可信文本处理。

高风险生产环境还需要独立解析 worker、系统调用/网络沙箱、病毒扫描和 CPU/内存/页数限制。

### SSRF 与恶意网页

URL importer 禁止非 HTTP(S)、嵌入凭据、回环/私网/链路本地/特殊地址；检查初始 URL、重定向目标和最终响应，并限制 content type、bytes 与 timeout。应用层检查不能替代网络层 egress policy，特别是 DNS rebinding、代理配置错误和云 metadata 新地址需要持续测试。

### Prompt injection 与不可信内容

检索到的文档可能包含“忽略系统指令”等文本。当前 evidence gate 和引用约束降低无依据回答，但**不等于完成 prompt-injection 防护**。接入真实生成模型时应把证据明确标记为数据、禁止其触发工具/网络动作、限制工具 allowlist，并为高风险动作设置用户确认和独立授权。

### 认证与租户越权

可选 bearer token 适合单实例 Beta，不包含用户身份、角色、会话撤销或 workspace 级授权。若多个团队共享实例，必须先实现服务端 workspace scope，并确保所有文档、chunk、历史、反馈、卡片、评测和日志查询都带授权过滤；前端筛选不是安全边界。

### 资源耗尽

进程内限流返回 `Retry-After`，网络调用有 timeout，前端支持 Abort。索引任务有 SQLite 租约、最大尝试和阶段取消，但只保证单实例；生产需要 Redis/网关限流、外部队列配额、并发/文档页数限制、provider budget 和隔离 worker。

### 敏感日志与错误

安全日志会清理 Authorization、token、password、secret 以及 URL query/fragment；外部 provider 错误经过脱敏再返回。仍需避免业务代码直接记录原文、请求体或本地绝对路径，并在可观测性平台设置字段 allowlist 和保留期限。

## 安全验证清单

- 上传：路径穿越、空文件、超限、扩展名/签名不匹配、DOCX ZIP bomb、解析失败清理。
- 任务：重复请求、租约恢复、三次尝试、取消/重试、暂存路径不出现在 API。
- URL：localhost、私网 IP、十进制/IPv6 变体、DNS/重定向、超大/错误类型、超时。
- API：缺失/错误 token、限流窗口、`Retry-After`、request ID 透传。
- 删除：只删除目标 document chunk/registry/source，不能越过 upload 根目录。
- 日志：Token、URL query、provider 异常和测试 fixture 均不泄漏敏感值。
- UI：错误可读但不展示秘密；取消不当作失败；重试不重复破坏性操作。
- 供应链：依赖锁定、CI secret 最小权限、镜像扫描和 SBOM 由发布流程执行。

## 报告漏洞

不要在公开 issue 中附带真实文档、Token 或私有 URL。请按 [SECURITY.md](../SECURITY.md) 使用 GitHub Private Security Advisory。生产上线前还应完成外部渗透测试、恢复演练和数据处理审查。
