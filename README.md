# AstrBot Deep Research Plugin

一个功能强大的深度研究插件，能够根据用户问题进行多阶段的网络研究并生成详细报告。

## 🔧 功能特性

### 🎯 核心功能
- **多阶段研究流程**：查询处理 → 信息检索 → 内容分析 → 报告生成
- **智能查询扩展**：自动分解复杂问题，生成多维度搜索词
- **多源信息聚合**：同时使用多个搜索引擎获取全面信息
- **内容深度分析**：LLM驱动的内容总结和关联分析
- **可视化报告**：自动生成精美的图片格式研究报告

### 🔍 搜索引擎支持（8个引擎）
- **百度搜索**：中文内容搜索效果优秀，支持重定向链接解析
- **Bing搜索**：国际化内容，覆盖面广，改进页面解析
- **DuckDuckGo官方**：隐私保护，无追踪，使用官方库
- **DuckDuckGo备用**：🆕 使用Peckot API，作为官方库的备用方案
- **Google API搜索**：需要配置API密钥，结果质量高
- **搜狗搜索**：🆕 中文搜索引擎，补充搜索来源
- **360搜索**：🆕 中文搜索引擎，改进页面解析器
- **DuckDuckGo抓取**：网页抓取版本，备用选择

### 🛠️ 技术特性
- **并发处理**：8个搜索引擎并行搜索，大幅提升效率
- **智能重试**：🆕 API调用失败自动重试，指数退避延迟
- **速率限制处理**：🆕 智能识别速率限制错误并重试
- **错误容错**：单个引擎失败不影响整体流程
- **内容解析**：智能HTML解析和文本提取
- **URL解析**：🆕 支持百度重定向、短链接等URL解析
- **去重优化**：自动去除重复搜索结果
- **模块化设计**：完全重构，易于扩展和维护

### 📊 四阶段研究流程

1. **查询处理与扩展** - 使用LLM解析用户问题，生成多个搜索关键词
2. **信息检索与筛选** - 并发使用8个搜索引擎，LLM智能筛选相关链接
3. **内容处理与分析** - 抓取网页内容，LLM生成摘要并聚合分析
4. **报告生成与交付** - 生成Markdown报告并渲染为图片

## 🚀 最新优化（v0.2.0）

### ✨ 新增功能
- **🆕 DuckDuckGo Peckot API**：新增基于Peckot API的DuckDuckGo搜索引擎
- **🆕 搜狗搜索引擎**：新增搜狗搜索，提升中文搜索覆盖
- **🆕 360搜索引擎**：新增360搜索，增加中文搜索来源
- **🆕 智能重试机制**：API调用失败自动重试，指数退避策略
- **🆕 速率限制处理**：智能识别并处理LLM API速率限制
- **🆕 URL解析器系统**：支持百度重定向、短链接等URL解析

### 🔧 重大改进
- **页面解析优化**：改进Bing和360搜索的页面解析器
- **搜索引擎架构**：完全模块化设计，支持8个搜索引擎并发
- **配置系统重构**：统一配置管理，支持引擎优先级设置
- **输出格式系统**：支持图片、Markdown、HTML等多种输出格式
- **错误处理完善**：分层异常处理，提升稳定性

### 🏆 性能提升
- **并发搜索**：从1个引擎提升到8个引擎并发搜索
- **搜索效率**：单次研究可执行最多40次并发搜索API调用
- **容错能力**：即使多个引擎失败也能继续工作
- **重试机制**：API失败自动重试，提升成功率

## 使用方法

### 基本命令
```
/deepresearch <查询内容>
/研究 <查询内容>
/深度研究 <查询内容>
```

### 示例
```
/deepresearch 人工智能的未来发展趋势
/研究 Python编程最佳实践
/深度研究 区块链技术应用场景
```

## 配置说明

### 默认配置
```json
{
  "max_search_results_per_term": 8,
  "max_terms_to_search": 5,
  "max_selected_links": 50,
  "max_content_length": 6000,
  "fetch_timeout": 30.0,
  "default_output_format": "image",
  "enable_url_resolution": true,
  "enable_parallel_processing": true,
  "engine_config": {}
}
```

### 搜索引擎配置
```json
{
  "engine_config": {
    "google_api": {
      "api_key": "你的Google API Key",
      "cse_id": "你的Google CSE ID"
    }
  }
}
```

### 配置参数说明
- `max_search_results_per_term`: 每个搜索词最多获取的结果数（默认8）
- `max_terms_to_search`: 最多使用几个搜索词进行搜索（默认5）
- `max_selected_links`: 最多处理几个筛选后的链接（默认50）
- `max_content_length`: 单个网页内容最大长度（默认6000字符）
- `enable_url_resolution`: 是否启用URL解析（默认true）
- `enable_parallel_processing`: 是否启用并发处理（默认true）

## 测试

### 测试搜索引擎
```bash
python test_search.py
```

### 测试完整功能
```bash
python test_deepresearch.py
```

### 测试新增功能
```bash
python test_new_features.py
```

### 测试优化功能
```bash
python test_optimizations.py
```

## 工作状态

### ✅ 正常工作的功能（已测试）
- ✅ 百度搜索引擎（支持重定向解析）
- ✅ Bing搜索引擎（改进页面解析）
- ✅ DuckDuckGo官方API
- ✅ DuckDuckGo Peckot API（新增）
- ✅ 搜狗搜索引擎（新增）
- ✅ 360搜索引擎（新增）
- ✅ 8引擎并发搜索
- ✅ 智能重试和速率限制处理
- ✅ URL解析器系统
- ✅ 搜索结果去重和格式化
- ✅ 错误处理和日志记录

### ⚠️ 需要配置的功能
- Google API搜索需要配置有效的API密钥
- DuckDuckGo抓取版本可能受网络环境影响

### 🔧 技术架构

#### 核心模块
```
astrbot_plugin_deepresearch/
├── main.py                 # 主插件逻辑和四阶段流程
├── config/                 # 配置管理模块
│   ├── __init__.py
│   └── settings.py         # 配置常量和默认值
├── search_engine_lib/      # 搜索引擎库
│   ├── __init__.py         # 引擎注册和管理
│   ├── base.py            # 搜索引擎基类
│   ├── models.py          # 数据模型定义
│   └── engines/           # 搜索引擎实现
│       ├── baidu_scrape_search.py
│       ├── bing_scrape_search.py
│       ├── duckduckgo_api_search.py
│       ├── duckduckgo_peckot_search.py  # 新增
│       ├── duckduckgo_scrape_search.py
│       ├── google_api_search.py
│       ├── sogou_scrape_search.py       # 新增
│       └── so360_scrape_search.py       # 新增
├── url_resolver/           # URL解析器系统
│   ├── __init__.py
│   ├── base.py            # 解析器基类
│   ├── resolvers.py       # 具体解析器实现
│   └── manager.py         # 解析器管理器
├── output_format/          # 输出格式系统
│   ├── __init__.py
│   ├── base.py            # 格式化器基类
│   ├── formatters.py      # 具体格式化器
│   └── manager.py         # 格式管理器
└── core/                  # 核心工具
    └── constants.py       # 常量定义
```

#### 搜索引擎优先级
1. 百度搜索（优先级1）- 中文搜索效果好
2. Bing搜索（优先级2）- 国际化内容
3. DuckDuckGo官方（优先级3）- 隐私友好
4. DuckDuckGo备用（优先级4）- Peckot API
5. 搜狗搜索（优先级5）- 中文搜索
6. 360搜索（优先级6）- 中文搜索
7. Google API（优先级4，默认禁用）- 需要API密钥


## 版本信息

- **版本**: 0.2.0
- **作者**: lxfight
- **最后更新**: 2025-06-13
- **主要更新**: 新增3个搜索引擎，智能重试，速率限制处理，URL解析器

## 更新日志

### v0.2.0 (2025-06-13)
- ✨ 新增DuckDuckGo Peckot API搜索引擎
- ✨ 新增搜狗搜索引擎
- ✨ 新增360搜索引擎
- ✨ 新增智能重试和速率限制处理
- ✨ 新增URL解析器系统
- 🔧 改进Bing和360搜索页面解析器
- 🔧 完全重构模块化架构
- 🔧 优化配置管理系统
- 🔧 增强错误处理和日志记录

### v0.1.0 (2025-06-12)
- 🎉 初始版本发布
- ✅ 实现四阶段研究流程
- ✅ 支持百度、Bing、DuckDuckGo、Google搜索
- ✅ 基本的并发搜索和内容分析

---

🎉 **重构成功！插件现在支持8个搜索引擎并发搜索，具备智能重试和完善的错误处理机制。**

如有问题或建议，请查看日志输出或联系开发者。
