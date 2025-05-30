import asyncio
import uuid
from typing import Dict, List, Any

import astrbot.api.star as star
import astrbot.api.event.filter as filter
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api import (
    logger,
    AstrBotConfig,
)

# 导入自定义的数据模型和任务管理器
from deepresearch.data_models import UserResearchQuery, ResearchReport, DeepResearchTask
from deepresearch.task_manager import TaskManager
from deepresearch.output_formatter.report_formatter import (
    ReportFormatter,
)  # 仅用于dr.output指令


@star.register(
    name="astrbot-deepresearch",
    desc="让 LLM 具有 deepresearch 能力，进行多源信息检索、内容筛选、深度分析与报告生成。",
    author="lxfight",
    version="1.919.810",
    repo="https://github.com/your_username/astrbot-deepresearch",  # 替换为您的实际仓库地址
)
class DeepResearch(star.Star):
    """开发版 deepresearch 插件，提供深度研究能力"""

    def __init__(self, context: star.Context, config: AstrBotConfig) -> None:
        super().__init__(context)  # 确保调用基类的 __init__
        self.config = config
        self.logger = logger
        self.task_manager = TaskManager(context, config)
        # 用于跟踪每个用户/会话正在进行的任务ID
        # key: event.unified_msg_origin (会话唯一ID)
        # value: task_id (深度研究任务ID)
        self.user_active_tasks: Dict[str, str] = {}
        self.logger.info("DeepResearch 插件初始化完成。")

    async def terminate(self):
        """
        当插件被卸载/停用时调用，用于清理资源。
        """
        self.logger.info("DeepResearch 插件正在终止...")
        # 尝试取消所有正在运行的后台任务
        for task_id, future in list(self.task_manager.task_futures.items()):
            if not future.done():
                self.logger.warning(f"终止时取消未完成的深度研究任务: {task_id}")
                future.cancel()  # 请求取消任务
                try:
                    await future  # 等待任务真正结束 (或抛出 CancelledError)
                except asyncio.CancelledError:
                    self.logger.info(f"任务 {task_id} 已被取消。")
                except Exception as e:
                    self.logger.error(
                        f"取消任务 {task_id} 时发生错误: {e}", exc_info=True
                    )
            self.task_manager.cleanup_task(task_id)  # 确保清理 future 引用
        self.logger.info("DeepResearch 插件已成功终止，所有活跃任务均已处理。")
        await super().terminate()  # 调用基类的 terminate 方法

    @filter.command(
        "deepresearch", alias={"dr", "研究", "深度研究"}, desc="启动一项深度研究任务"
    )
    async def start_deep_research(self, event: AstrMessageEvent, query: str):
        """
        处理 /deepresearch 命令，启动一个深度研究任务。
        用法：/deepresearch [您的研究问题]
        """
        user_id = event.get_sender_id()
        umo = event.unified_msg_origin  # 会话唯一标识符

        if umo in self.user_active_tasks:
            existing_task_id = self.user_active_tasks[umo]
            # 检查任务是否仍在运行
            task = self.task_manager.get_task_status(existing_task_id)
            if task and task.status not in ["completed", "failed"]:
                yield event.plain_result(
                    f"您已有一个正在进行的深度研究任务（ID: `{existing_task_id[:8]}`），请等待其完成或使用 `/dr status {existing_task_id[:8]}` 查看进度。"
                )
                return
            else:
                # 如果任务已完成或失败，清理旧引用
                del self.user_active_tasks[umo]

        self.logger.info(f"用户 {user_id} 发起新的深度研究请求: '{query}'")

        # 创建用户查询对象
        user_query_obj = UserResearchQuery(core_query=query, user_id=user_id)

        # 启动后台的深度研究任务
        task_id = await self.task_manager.start_research_task(user_query_obj, event)
        self.user_active_tasks[umo] = task_id  # 记录当前会话的任务ID

        yield event.plain_result(
            f"您的深度研究任务已启动！任务ID: `{task_id[:8]}`。请耐心等待结果，您可以使用 `/dr status {task_id[:8]}` 查看进度。"
        )

    @filter.command("dr.status", desc="查看深度研究任务的当前状态")
    async def get_dr_status(self, event: AstrMessageEvent, task_id: str):
        """
        处理 /dr.status 命令，查询指定任务ID的深度研究状态。
        用法：/dr.status [任务ID]
        """
        task = self.task_manager.get_task_status(task_id)
        if task:
            status_message = (
                f"💡 深度研究任务状态\n"
                f"ID: `{task.task_id[:8]}`\n"
                f"原始查询: `{task.user_query.core_query}`\n"
                f"当前状态: `{task.status}`\n"
                f"启动时间: `{task.created_at.strftime('%Y-%m-%d %H:%M:%S')}`\n"
            )
            if task.status == "failed" and task.error_message:
                status_message += f"错误信息: `{task.error_message}`\n"
            elif task.status == "completed" and task.final_report:
                status_message += f"报告标题: `{task.final_report.main_title}`\n"
                status_message += (
                    f"报告已生成，可以使用 `/dr output {task.task_id[:8]} [格式]` 获取。\n"
                    f"支持格式：`md` (默认), `html`, `image`。"
                )

            yield event.plain_result(status_message)
        else:
            yield event.plain_result(
                f"未找到任务ID为 `{task_id[:8]}` 的深度研究任务。请检查ID是否正确。"
            )

    @filter.command("dr.output", desc="获取深度研究报告的指定格式输出")
    async def get_dr_output(
        self, event: AstrMessageEvent, task_id: str, format_type: str = ""
    ):
        """
        处理 /dr.output 命令，获取指定任务ID的研究报告输出。
        用法：/dr.output [任务ID] [格式, 默认为md]
        支持格式：md, html, image
        """
        task = self.task_manager.get_task_status(task_id)
        if not task:
            yield event.plain_result(f"未找到任务ID为 `{task_id[:8]}` 的深度研究任务。")
            return

        if task.status != "completed" or not task.final_report:
            yield event.plain_result(
                f"任务 `{task_id[:8]}` 尚未完成或报告未生成。当前状态：`{task.status}`。"
            )
            return

        # 如果用户没有指定格式，使用插件默认配置
        if not format_type:
            format_type = self.config.get("output_config", {}).get(
                "default_output_format", "md"
            )

        self.logger.info(f"用户请求任务 {task_id} 的报告输出，格式: {format_type}")
        await self.task_manager._send_report_output(
            event, task.final_report, task_id, format_type
        )

        # 报告输出后，可以清理用户会话的任务跟踪
        umo = event.unified_msg_origin
        if umo in self.user_active_tasks and self.user_active_tasks[umo] == task_id:
            del self.user_active_tasks[umo]
            self.logger.info(f"会话 {umo} 的任务 {task_id} 已输出，从跟踪列表中移除。")

    @filter.command("dr.cleanup", desc="清理已完成或失败的研究任务在内存中的记录")
    async def cleanup_dr_task(self, event: AstrMessageEvent, task_id: str):
        """
        处理 /dr.cleanup 命令，手动清理指定任务ID在内存中的记录。
        用法：/dr.cleanup [任务ID]
        """
        task = self.task_manager.get_task_status(task_id)
        if not task:
            yield event.plain_result(f"未找到任务ID为 `{task_id[:8]}` 的深度研究任务。")
            return

        self.task_manager.cleanup_task(task_id)
        # 尝试清理用户会话跟踪
        for umo, tid in list(self.user_active_tasks.items()):
            if tid == task_id:
                del self.user_active_tasks[umo]
                break

        yield event.plain_result(f"任务 `{task_id[:8]}` 的内存记录已清理。")
