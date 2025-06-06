# 搜索引擎的异常定义


class SearchEngineError(Exception):
    """搜索引擎库的基础异常类"""

    pass


class RegistrationError(SearchEngineError):
    """搜索引擎注册失败时抛出"""

    pass


class ConfigurationError(SearchEngineError):
    """当搜索引擎配置不完整或错误时抛出"""

    pass
