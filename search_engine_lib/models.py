from typing import List, Optional
from pydantic import BaseModel, Field, HttpUrl


class SearchQuery(BaseModel):
    """
    搜索引擎的输入模型。
    规范了所有发送给搜索引擎的请求。
    """

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="要搜索的关键词或句子。",
    )
    count: int = Field(
        default=10,
        gt=0,
        le=50,
        description="期望返回的搜索结果数量。",
    )


class SearchResultItem(BaseModel):
    """
    单个搜索结果的输出模型。
    规范了每一个返回的结果条目。
    """

    title: str = Field(..., description="结果的标题。")
    link: HttpUrl = Field(..., description="结果的URL链接。")
    snippet: str = Field(..., description="结果的摘要或描述。")


class SearchResponse(BaseModel):
    """
    搜索引擎的最终输出模型。
    这是一个完整的响应包，包含了结果列表和元数据。
    """

    query: SearchQuery = Field(..., description="用于本次搜索的原始查询对象。")
    engine_name: str = Field(..., description="执行本次搜索的引擎名称。")
    results: List[SearchResultItem] = Field(..., description="搜索结果的列表。")

    search_time_seconds: float = Field(
        ...,
        ge=0,  # 'ge' 表示大于或等于 0
        description="执行本次搜索所花费的时间（秒）。",
    )
    estimated_total_results: Optional[int] = Field(
        default=None, description="搜索引擎估算的总结果数（如果可用）。"
    )
