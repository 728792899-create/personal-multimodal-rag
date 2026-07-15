# 版面与 OCR 固定证据

LAY-01：第 1 页标题框 bbox [72,48,540,96]，标题为 Durable Indexing。

LAY-02：第 2 页双栏正文的阅读顺序是左栏 AlphaColumn 先于右栏 BetaColumn。

LAY-03：扫描页 OCR 识别出请求标识 Request-7F3A，置信度 0.94。

LAY-04：页脚 Footnote-Delta 归属于引用段落 CitationPolicy，不应拼到标题。

LAY-05：图片 Caption-Echo 位于图像下方 12 像素，与 Asset-Echo 对齐。

LAY-06：表格 Table-Foxtrot 的表头跨页重复，合并后只保留一次 Header-F。

LAY-07：公式 Equation-Golf 位于段落 EnergyModel 之后，顺序索引为 17。

LAY-08：代码块 Code-Hotel 保留四个空格缩进和语言标记 python。

LAY-09：竖排标签 Vertical-India 被标记为边栏注释，不参与正文分块。

LAY-10：印章 Stamp-Juliet 的 OCR 文本为 APPROVED，但版面告警标记为 low_contrast。

LAY-11：页面旋转 90 度后 Rotation-Kilo 恢复水平阅读，OCR 置信度 0.89。

LAY-12：孤立资源 Asset-Lima 没有 caption 或正文引用，质量面板应记录 orphan_asset。
