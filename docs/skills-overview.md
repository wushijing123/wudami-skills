# Wudami Skill 解读

## `wudami-content-workflow`

吴大咪内容生产总入口。负责找选题、判断平台、写小红书脚本、写公众号文章、生成标题、优化开头、生成正文。适合所有“帮我创作内容”“写稿子”“找选题”类需求。

## `wudami-jiaoben-api`

短视频文案提取和脚本拆解工具。给它一个视频链接，它会提取视频口播，再把内容拆成结构、钩子、表达方式和可复用脚本分析。

## `wudami-lark-single-video-api`

极简版单条视频口播提取器。重点不是生成报告，而是安静地输出一条干净口播文本，适合接入飞书多维表格自动补字段。

## `wudami-live-teleprompter`

直播投屏器生成工具。把文档、大纲、Markdown、DOCX 或 HTML 转成演示 slides 和口播稿，方便直播、课程、OBS 投屏使用。

## `wudami-xhs-account-analyzer`

手动资料版小红书账号拆解。用户提供账号信息、近期笔记数据、截图、爆款笔记和变现信息后，它负责分析这个账号为什么能爆、内容结构怎么做、人设和变现路径是什么。

## `wudami-xhs-analyzer-claw`

自动抓取版小红书账号拆解。它会通过独立浏览器抓取账号主页和全量笔记，再生成账号分析报告、内容维度归类和可视化页面。

## `wudami-xhs-account-analyzer_scraper`

嵌套在 `wudami-xhs-analyzer-claw` 里的补充 Skill。主要说明 API 方式抓取小红书账号数据的路线，用来辅助账号拆解。

## `wudami-xhs-koubo-all`

小红书博主全量笔记扫描和精选爆款提纯工具。第一步先拉博主全部笔记清单，第二步再挑选指定笔记提取口播、封面、正文和爆款要素。

## `wudami-xhs-note-analyzer-api`

API 版单篇小红书笔记深度拆解。适合不想开浏览器、不想手动登录时使用，直接通过接口抓笔记详情、评论和素材，再生成深度拆解报告。

## `wudami-xhs-note-analyzer-cdp`

浏览器版单篇小红书笔记深度拆解。适合用已登录的小红书浏览器抓取单篇笔记，能分析正文、图片、评论、视频口播和爆款结构。

## `wudami-xhs-scraper-api`

多平台数据抓取 Skill。统一处理小红书、抖音、TikTok、B站、微博、公众号、视频号、X、YouTube 等平台的数据抓取需求。

## `wudami-xhs-video-diagnostic-api`

短视频风控和限流诊断工具。用于发布前检查视频有没有违规、硬广、拉踩、夸大表达等风险，也可以用于发布后复盘为什么没流量。

## `wudami-xhs-viral-analyzer`

小红书低粉爆款扫描和脚本生成器。通过关键词搜索找低粉高赞笔记，提炼爆款角度、评论区痛点和脚本框架，适合找选题和做洗稿参考。

## `wudami-zsxq-sync`

知识星球内容同步工具。把知识星球星主内容抓取出来，做摘要、分类、去重，然后同步到飞书多维表格。

