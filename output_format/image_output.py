# TODO 这里实现基于AstrBot的HTML转图片输出格式转换并输出

# 这里需要获取到 AstrBot 的事件对象 AstrMessageEvent
# 通过事件对象直接构造消息链实现消息的发送，并更新任务状态
from ..core.task_manager import TaskStatus, Task
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api import logger


class ImageOutputFormatter:
    @staticmethod
    def format_image_output(event: AstrMessageEvent, task: Task):
        """
        格式化图片输出，并发送消息。

        :param event: 触发任务的事件对象
        :param task: 任务对象
        """
        pass
