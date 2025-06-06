# TODO 这里需要实现一个任务管理器，负责管理任务的状态和执行流程
import uuid
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from pydantic import BaseModel, Field


class Task(BaseModel):
    """
    任务模型，包含任务的基本信息和状态。
    """

    task_id: str = Field(..., description="任务的唯一标识符")
    query: str = Field(..., description="任务的查询内容")
    event: AstrMessageEvent = Field(..., description="触发任务的事件对象")
    status: str = Field(default="pending", description="任务的当前状态")
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
        task_id = str(uuid.uuid4())
        task = Task(task_id=task_id, query=query, status="pending", event=event)
        self.tasks[task_id] = task
        logger.info(f"创建任务: {task_id}，查询内容: {query}")


    def get_task_status(self, task_id: str):
        """
        获取任务的状态。
        """
        task = self.tasks.get(task_id)
        if task:
            return task.status
        return "任务不存在"

    def delete_task(self, task_id: str):
        """
        删除一个任务。
        """
        task = self.tasks.pop(task_id, None)
        if task:
            logger.info(f"删除任务: {task_id}")
            return task
        return "任务不存在"

    def list_tasks(self):
        """
        列出所有任务。
        """
        return self.tasks

    # 清理已经完成的任务记录
    def cleanup_completed_tasks(self):
        """
        清理已经完成的任务记录。
        """
