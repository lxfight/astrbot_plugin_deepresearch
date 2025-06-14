# config/settings.py
"""插件配置设置"""

# 默认配置
DEFAULT_CONFIG = {
    "max_search_results_per_term": 8,
    "max_terms_to_search": 5,
    "max_selected_links": 50,
    "max_content_length": 6000,
    "fetch_timeout": 30.0,
    "default_output_format": "image",
    "enable_url_resolution": True,
    "enable_parallel_processing": True,
    "engine_config": {}
}

# 支持的输出格式
SUPPORTED_OUTPUT_FORMATS = {
    "image": {
        "name": "图片报告",
        "description": "将Markdown报告渲染为图片",
        "extension": ".png"
    },
    "markdown": {
        "name": "Markdown文本",
        "description": "原始Markdown格式文本",
        "extension": ".md"
    },
    "html": {
        "name": "HTML页面",
        "description": "HTML格式报告",
        "extension": ".html"
    },
    "pdf": {
        "name": "PDF文档",
        "description": "PDF格式报告(未来支持)",
        "extension": ".pdf"
    }
}

# 搜索引擎配置
SEARCH_ENGINE_CONFIGS = {
    "baidu_scrape": {
        "enabled": True,
        "name": "百度搜索",
        "description": "通过抓取百度搜索页面提供结果，中文搜索效果好",
        "requires_api_key": False,
        "priority": 1
    },
    "bing_scrape": {
        "enabled": True,
        "name": "Bing搜索",
        "description": "通过抓取Bing搜索页面提供结果，国际化搜索",
        "requires_api_key": False,
        "priority": 2
    },
    "duckduckgo_api": {
        "enabled": True,
        "name": "DuckDuckGo搜索",
        "description": "使用官方DuckDuckGo API，隐私友好",
        "requires_api_key": False,
        "priority": 3
    },
    "duckduckgo_peckot": {
        "enabled": True,
        "name": "DuckDuckGo备用搜索",
        "description": "使用Peckot API的DuckDuckGo搜索，作为官方库的备用方案",
        "requires_api_key": False,
        "priority": 4
    },
    "google_api": {
        "enabled": False,
        "name": "Google API搜索",
        "description": "Google Custom Search API，需要配置密钥",
        "requires_api_key": True,
        "priority": 4
    },
    "sogou_scrape": {
        "enabled": True,
        "name": "搜狗搜索",
        "description": "搜狗搜索引擎，中文搜索",
        "requires_api_key": False,
        "priority": 5
    },
    "so360_scrape": {
        "enabled": True,
        "name": "360搜索",
        "description": "360搜索引擎，中文搜索",
        "requires_api_key": False,
        "priority": 6
    }
}

# URL解析器配置
URL_RESOLVER_CONFIGS = {
    "baidu_redirect": {
        "enabled": True,
        "pattern": r"baidu\.com/link",
        "description": "百度重定向链接解析"
    },
    "bing_redirect": {
        "enabled": True,
        "pattern": r"bing\.com/.*url=",
        "description": "Bing重定向链接解析"
    },
    "google_redirect": {
        "enabled": True,
        "pattern": r"google\.com/url",
        "description": "Google重定向链接解析"
    },
    "short_url": {
        "enabled": True,
        "pattern": r"(bit\.ly|tinyurl\.com|t\.co|short\.link)",
        "description": "短链接解析"
    }
}

# HTTP请求头
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

# HTML 报告模板，用于 html_render
HTML_REPORT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Deep Research Report</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
    line-height: 1.6;
    color: #333;
    background-color: #f9f9f9;
    padding: 20px;
    max-width: 900px;
    margin: 20px auto;
    border: 1px solid #eee;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    border-radius: 8px;
  }}
  h1, h2, h3 {{ color: #0056b3; border-bottom: 1px solid #eee; padding-bottom: 5px;}}
  h1 {{ text-align: center; }}
  a {{ color: #007bff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  pre {{ background-color: #eee; padding: 10px; border-radius: 4px; overflow-x: auto; }}
  code {{ background-color: #eee; padding: 2px 4px; border-radius: 3px; font-size: 0.9em;}}
  blockquote {{ border-left: 4px solid #ccc; padding-left: 15px; margin-left: 0; color: #555; font-style: italic;}}
   img {{ max-width: 100%; height: auto; }}
   ul, ol {{ padding-left: 25px; }}
   li {{ margin-bottom: 8px;}}
  .footer {{ margin-top: 30px; font-size: 0.8em; color: #777; text-align: center; border-top: 1px solid #eee; padding-top: 10px;}}
</style>
</head>
<body>
  <h1>深度研究报告</h1>
  {content}
  <div class="footer">Generated by AstrBot DeepResearch Plugin</div>
</body>
</html>
"""
