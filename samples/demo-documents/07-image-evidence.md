# 图像理解固定证据

本文档保存 12 个脱敏图像 fixture 的确定性 OCR 与 caption，供离线评测使用。

## IMG-01 检索漏斗
Caption IMG-01：蓝色检索漏斗从 48 个 BM25 候选缩减到 5 条引用证据。

## IMG-02 向量空间
Caption IMG-02：绿色向量空间中 QueryStar 靠近 EvidenceMoon，余弦相似度为 0.91。

## IMG-03 MMR 去重
Caption IMG-03：橙色 MMR 面板保留相关且不重复的 Alpha、Beta、Gamma 三个片段。

## IMG-04 引用覆盖
Caption IMG-04：引用环形图显示 8 个声明中 7 个被证据支持，覆盖率 87.5%。

## IMG-05 拒答门
Caption IMG-05：红色拒答门在置信度 0.03 低于阈值 0.05 时阻止生成。

## IMG-06 索引队列
Caption IMG-06：队列看板依次显示 queued、running、quality 和 succeeded 四个阶段。

## IMG-07 文档元素
Caption IMG-07：页面线框按顺序标注 heading、paragraph、table 和 equation 四类元素。

## IMG-08 图谱路径
Caption IMG-08：证据图显示 RouterNode 通过 uses 连到 RankerNode，再通过 supports 连到 CitationNode。

## IMG-09 Provider 健康
Caption IMG-09：Provider 健康卡中 template 和 mock 为 ready，OpenAI 为 not_configured。

## IMG-10 窄屏布局
Caption IMG-10：390 像素窄屏下知识库、提问和审计面板按单列排列。

## IMG-11 错误恢复
Caption IMG-11：504 错误卡显示 request ID、重试按钮和已保留的问题文本。

## IMG-12 反馈闭环
Caption IMG-12：负反馈箭头从 bad_answer 流向 eval draft，再流向固定回归集。
