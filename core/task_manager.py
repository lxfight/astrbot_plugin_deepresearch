# TODO 这里需要实现一个任务管理器，负责管理任务的状态和执行流程
import uuid
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from pydantic import BaseModel, Field
from enum import Enum


# 定义一个状态枚举类型
class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class Task(BaseModel):
    """
    任务模型，包含任务的基本信息和状态。
    """

    task_id: str = Field(..., description="任务的唯一标识符")
    query: str = Field(..., description="任务的查询内容")
    event: AstrMessageEvent = Field(..., description="触发任务的事件对象")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="任务的当前状态")
    result: str = Field(default=None, description="任务执行结果，如果有的话")
    error_message: str = Field(default=None, description="如果任务失败，记录错误信息")


class TaskManager:
    def __init__(self):
        self.tasks: dict[
            str, Task
        ] = {}  # 存储任务的字典，key为task_id，value为Task对象

    async def create_task(
        self,
        event: AstrMessageEvent,
        query: str,
    ):
        """
        从这里开始, 创建一个新的任务。
        """
        if not query:
            logger.error("查询内容不能为空")
            event.send(MessageChain.message("查询内容不能为空"))
            return

        if len(query) > 1000:
            logger.error("查询内容过长，不能超过1000个字符")
            event.send(MessageChain.message("查询内容过长，不能超过1000个字符"))
            return

        if not isinstance(event, AstrMessageEvent):
            logger.error("事件对象必须是AstrMessageEvent类型")
            event.send(MessageChain.message("事件对象必须是AstrMessageEvent类型"))
            return

        task_id = str(uuid.uuid4())
        logger.debug(f"为{event.unified_msg_origin}，生成任务ID: {task_id}")
        task = Task(task_id=task_id, query=query, status="pending", event=event)
        self.tasks[task_id] = task
        logger.info(f"创建任务: {task_id}，查询内容: {query}")

    async def get_task_status(self, task_id: str):
        """
        获取任务的状态。
        """
        task = self.tasks.get(task_id)
        if task:
            return task.status
        return "任务不存在"

    async def delete_task(self, task_id: str):
        """
        删除一个任务。
        """
        task = self.tasks.pop(task_id, None)
        if task:
            logger.info(f"删除任务: {task_id}")
            return task
        return "任务不存在"

    async def list_tasks(self):
        """
        列出所有任务。
        """
        return self.tasks

    # 清理已经完成的任务记录
    async def cleanup_completed_tasks(self):
        """
        清理已经完成的任务记录。
        """
        completed_tasks = [
            task_id
            for task_id, task in self.tasks.items()
            if task.status == TaskStatus.COMPLETED or task.status == TaskStatus.FAILED
        ]
        for task_id in completed_tasks:
            self.tasks.pop(task_id, None)
            logger.info(f"清理完成的任务: {task_id}")
