import asyncio
import json
from pathlib import Path
from datetime import datetime

from typing import Dict

import astrbot.api.star as star
import astrbot.api.event.filter as filter
from astrbot.api.event import AstrMessageEvent
from astrbot.api import (
    logger,
    AstrBotConfig,
)

# 导入自定义的数据模型和任务管理器
from .deepresearch.data_models import UserResearchQuery
from .deepresearch.task_manager import TaskManager


@star.register(
    name="astrbot-deepresearch",
    desc="让 LLM 具有 deepresearch 能力，进行多源信息检索、内容筛选、深度分析与报告生成。",
    author="lxfight",
    version="1.919.810",
    repo="https://github.com/lxfight/astrbot_plugin_deepresearch",
)
class DeepResearch(star.Star):
    """开发版 deepresearch 插件，提供深度研究能力"""

    def __init__(self, context: star.Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self.logger = logger

        # 初始化持久化存储路径
        self.data_dir = Path(__file__).parent / "data"
        self.data_dir.mkdir(exist_ok=True)
        self.tasks_file = self.data_dir / "active_tasks.json"
        self.performance_file = self.data_dir / "performance_metrics.json"

        # 初始化任务管理器
        try:
            self.task_manager = TaskManager(context, config)
            self.logger.info("任务管理器初始化成功")
        except Exception as e:
            self.logger.error(f"任务管理器初始化失败: {e}", exc_info=True)
            raise

        # 用于跟踪每个用户/会话正在进行的任务ID
        # key: event.unified_msg_origin (会话唯一ID)
        # value: task_id (深度研究任务ID)
        self.user_active_tasks: Dict[str, str] = {}

        # 性能监控数据
        self.performance_metrics = {
            "total_tasks_created": 0,
            "total_tasks_completed": 0,
            "total_tasks_failed": 0,
            "average_completion_time": 0.0,
            "last_updated": datetime.now().isoformat(),
        }

        # 加载持久化数据
        self._load_persistent_data()

        self.logger.info("DeepResearch 插件初始化完成")

    def _load_persistent_data(self):
        """加载持久化数据"""
        try:
            # 加载活跃任务
            if self.tasks_file.exists():
                with open(self.tasks_file, "r", encoding="utf-8") as f:
                    self.user_active_tasks = json.load(f)
                self.logger.info(
                    f"已加载 {len(self.user_active_tasks)} 个持久化任务记录"
                )

            # 加载性能指标
            if self.performance_file.exists():
                with open(self.performance_file, "r", encoding="utf-8") as f:
                    self.performance_metrics.update(json.load(f))
                self.logger.info("已加载性能指标数据")

        except Exception as e:
            self.logger.error(f"加载持久化数据时出错: {e}", exc_info=True)

    async def _save_persistent_data(self):
        """保存持久化数据"""
        try:
            # 保存活跃任务
            with open(self.tasks_file, "w", encoding="utf-8") as f:
                json.dump(self.user_active_tasks, f, ensure_ascii=False, indent=2)

            # 更新并保存性能指标
            self.performance_metrics["last_updated"] = datetime.now().isoformat()
            with open(self.performance_file, "w", encoding="utf-8") as f:
                json.dump(self.performance_metrics, f, ensure_ascii=False, indent=2)

        except Exception as e:
            self.logger.error(f"保存持久化数据时出错: {e}", exc_info=True)

    def _update_performance_metrics(
        self, task_status: str, completion_time: float = None
    ):
        """更新性能指标"""
        try:
            if task_status == "created":
                self.performance_metrics["total_tasks_created"] += 1
            elif task_status == "completed":
                self.performance_metrics["total_tasks_completed"] += 1
                if completion_time:
                    # 更新平均完成时间
                    current_avg = self.performance_metrics["average_completion_time"]
                    total_completed = self.performance_metrics["total_tasks_completed"]
                    new_avg = (
                        (current_avg * (total_completed - 1)) + completion_time
                    ) / total_completed
                    self.performance_metrics["average_completion_time"] = round(
                        new_avg, 2
                    )
            elif task_status == "failed":
                self.performance_metrics["total_tasks_failed"] += 1
        except Exception as e:
            self.logger.error(f"更新性能指标时出错: {e}", exc_info=True)

    async def terminate(self):
        """
        当插件被卸载/停用时调用，用于清理资源。
        """
        self.logger.info("DeepResearch 插件正在终止...")

        # 保存持久化数据
        await self._save_persistent_data()

        # 尝试取消所有正在运行的后台任务
        cancelled_count = 0
        for task_id, future in list(self.task_manager.task_futures.items()):
            if not future.done():
                self.logger.warning(f"终止时取消未完成的深度研究任务: {task_id}")
                future.cancel()  # 请求取消任务
                try:
                    await asyncio.wait_for(
                        future, timeout=5.0
                    )  # 等待任务真正结束，设置超时
                except asyncio.CancelledError:
                    self.logger.info(f"任务 {task_id} 已被成功取消")
                    cancelled_count += 1
                except asyncio.TimeoutError:
                    self.logger.warning(f"任务 {task_id} 取消超时")
                except Exception as e:
                    self.logger.error(
                        f"取消任务 {task_id} 时发生错误: {e}", exc_info=True
                    )
            self.task_manager.cleanup_task(task_id)  # 确保清理 future 引用

        self.logger.info(
            f"DeepResearch 插件已成功终止，共取消了 {cancelled_count} 个活跃任务"
        )
        await super().terminate()  # 调用基类的 terminate 方法

    @filter.command(
        "deepresearch", alias={"dr", "研究", "深度研究"}, desc="启动一项深度研究任务"
    )
    async def start_deep_research(self, event: AstrMessageEvent, query: str):
        """
        处理 /deepresearch 命令，启动一个深度研究任务。
        用法：/deepresearch [您的研究问题]
        """
        if not query or query.strip() == "":
            yield event.plain_result(
                "❌ 请提供您要研究的问题。\n用法：/deepresearch [您的研究问题]"
            )
            return

        user_id = event.get_sender_id()
        umo = event.unified_msg_origin  # 会话唯一标识符

        # 检查是否有正在进行的任务
        if umo in self.user_active_tasks:
            existing_task_id = self.user_active_tasks[umo]
            try:
                # 检查任务是否仍在运行
                task = self.task_manager.get_task_status(existing_task_id)
                if task and task.status not in ["completed", "failed"]:
                    yield event.plain_result(
                        f"⚠️ 您已有一个正在进行的深度研究任务\n"
                        f"任务ID: `{existing_task_id[:8]}`\n"
                        f"当前状态: `{task.status}`\n"
                        f"请等待其完成或使用 `/dr status {existing_task_id[:8]}` 查看详细进度"
                    )
                    return
                else:
                    # 如果任务已完成或失败，清理旧引用
                    del self.user_active_tasks[umo]
                    self.logger.info(
                        f"清理用户 {user_id} 的已完成任务引用: {existing_task_id}"
                    )
            except Exception as e:
                self.logger.error(f"检查现有任务状态时出错: {e}", exc_info=True)
                # 清理可能损坏的引用
                del self.user_active_tasks[umo]

        self.logger.info(
            f"用户 {user_id} 发起新的深度研究请求: '{query[:100]}{'...' if len(query) > 100 else ''}'"
        )

        try:
            # 创建用户查询对象
            user_query_obj = UserResearchQuery(core_query=query, user_id=user_id)

            # 启动后台的深度研究任务
            task_id = await self.task_manager.start_research_task(user_query_obj, event)
            self.user_active_tasks[umo] = task_id  # 记录当前会话的任务ID

            # 更新性能指标
            self._update_performance_metrics("created")

            # 保存持久化数据
            await self._save_persistent_data()

            yield event.plain_result(
                f"🚀 您的深度研究任务已成功启动！\n"
                f"📋 任务ID: `{task_id[:8]}`\n"
                f"🔍 研究问题: `{query[:50]}{'...' if len(query) > 50 else ''}`\n"
                f"⏳ 预计完成时间: 2-5分钟\n\n"
                f"💡 使用以下命令查看进度：\n"
                f"• `/dr status {task_id[:8]}` - 查看详细状态\n"
                f"• `/dr list` - 查看所有任务\n"
                f"• `/dr help` - 查看所有可用命令"
            )

        except Exception as e:
            self.logger.error(f"启动深度研究任务时出错: {e}", exc_info=True)
            yield event.plain_result(
                f"❌ 启动研究任务时发生错误: {str(e)}\n请稍后重试或联系管理员"
            )

    @filter.command("dr.status", desc="查看深度研究任务的当前状态")
    async def get_dr_status(self, event: AstrMessageEvent, task_id: str):
        """
        处理 /dr.status 命令，查询指定任务ID的深度研究状态。
        用法：/dr.status [任务ID]
        """
        if not task_id:
            yield event.plain_result("❌ 请提供任务ID\n用法：/dr.status [任务ID]")
            return

        try:
            task = self.task_manager.get_task_status(task_id)
            if task:
                # 计算运行时间
                runtime = datetime.now() - task.created_at
                runtime_str = f"{runtime.total_seconds():.0f}秒"
                if runtime.total_seconds() > 60:
                    runtime_str = f"{runtime.total_seconds() / 60:.1f}分钟"

                # 状态图标映射
                status_icons = {
                    "pending": "⏳",
                    "running": "🔄",
                    "completed": "✅",
                    "failed": "❌",
                }

                status_message = (
                    f"{status_icons.get(task.status, '❓')} 深度研究任务状态\n\n"
                    f"📋 任务ID: `{task.task_id[:8]}`\n"
                    f"🔍 研究问题: `{task.user_query.core_query[:60]}{'...' if len(task.user_query.core_query) > 60 else ''}`\n"
                    f"📊 当前状态: `{task.status}`\n"
                    f"🕒 启动时间: `{task.created_at.strftime('%Y-%m-%d %H:%M:%S')}`\n"
                    f"⏱️ 运行时长: `{runtime_str}`\n"
                )

                if task.status == "failed" and task.error_message:
                    status_message += f"💥 错误信息: `{task.error_message}`\n"
                elif task.status == "completed" and task.final_report:
                    status_message += (
                        f"📄 报告标题: `{task.final_report.main_title}`\n"
                        f"📊 报告章节数: `{len(task.final_report.sections) if hasattr(task.final_report, 'sections') else '未知'}`\n\n"
                        f"🎯 获取报告命令：\n"
                        f"• `/dr output {task.task_id[:8]}` - Markdown格式\n"
                        f"• `/dr output {task.task_id[:8]} html` - HTML格式\n"
                        f"• `/dr output {task.task_id[:8]} image` - 图片格式"
                    )
                elif task.status == "running":
                    status_message += "🔄 任务正在执行中，请耐心等待..."

                yield event.plain_result(status_message)
            else:
                yield event.plain_result(
                    f"❌ 未找到任务ID为 `{task_id[:8]}` 的深度研究任务\n"
                    f"💡 使用 `/dr list` 查看所有可用任务"
                )
        except Exception as e:
            self.logger.error(f"查询任务状态时出错: {e}", exc_info=True)
            yield event.plain_result(f"❌ 查询任务状态时发生错误: {str(e)}")

    @filter.command("dr.output", desc="获取深度研究报告的指定格式输出")
    async def get_dr_output(
        self, event: AstrMessageEvent, task_id: str, format_type: str = ""
    ):
        """
        处理 /dr.output 命令，获取指定任务ID的研究报告输出。
        用法：/dr.output [任务ID] [格式, 默认为md]
        支持格式：md, html, image
        """
        if not task_id:
            yield event.plain_result(
                "❌ 请提供任务ID\n用法：/dr.output [任务ID] [格式]"
            )
            return

        try:
            task = self.task_manager.get_task_status(task_id)
            if not task:
                yield event.plain_result(
                    f"❌ 未找到任务ID为 `{task_id[:8]}` 的深度研究任务"
                )
                return

            if task.status != "completed" or not task.final_report:
                yield event.plain_result(
                    f"⚠️ 任务 `{task_id[:8]}` 尚未完成或报告未生成\n"
                    f"📊 当前状态：`{task.status}`\n"
                    f"💡 使用 `/dr status {task_id[:8]}` 查看详细信息"
                )
                return

            # 如果用户没有指定格式，使用插件默认配置
            if not format_type:
                format_type = self.config.get("output_config", {}).get(
                    "default_output_format", "md"
                )

            self.logger.info(f"用户请求任务 {task_id} 的报告输出，格式: {format_type}")

            # 发送报告
            await self.task_manager._send_report_output(
                event, task.final_report, task_id, format_type
            )

            # 报告输出后，可以清理用户会话的任务跟踪
            umo = event.unified_msg_origin
            if umo in self.user_active_tasks and self.user_active_tasks[umo] == task_id:
                del self.user_active_tasks[umo]
                await self._save_persistent_data()
                self.logger.info(
                    f"会话 {umo} 的任务 {task_id} 已输出，从跟踪列表中移除"
                )

        except Exception as e:
            self.logger.error(f"获取报告输出时出错: {e}", exc_info=True)
            yield event.plain_result(f"❌ 获取报告时发生错误: {str(e)}")

    @filter.command("dr.cleanup", desc="清理已完成或失败的研究任务在内存中的记录")
    async def cleanup_dr_task(self, event: AstrMessageEvent, task_id: str):
        """
        处理 /dr.cleanup 命令，手动清理指定任务ID在内存中的记录。
        用法：/dr.cleanup [任务ID]
        """
        if not task_id:
            yield event.plain_result("❌ 请提供任务ID\n用法：/dr.cleanup [任务ID]")
            return

        try:
            task = self.task_manager.get_task_status(task_id)
            if not task:
                yield event.plain_result(
                    f"❌ 未找到任务ID为 `{task_id[:8]}` 的深度研究任务"
                )
                return

            # 清理任务管理器中的记录
            self.task_manager.cleanup_task(task_id)

            # 尝试清理用户会话跟踪
            cleaned_sessions = 0
            for umo, tid in list(self.user_active_tasks.items()):
                if tid == task_id:
                    del self.user_active_tasks[umo]
                    cleaned_sessions += 1

            # 保存持久化数据
            await self._save_persistent_data()

            yield event.plain_result(
                f"✅ 任务 `{task_id[:8]}` 的内存记录已清理完成\n"
                f"🧹 清理了 {cleaned_sessions} 个会话引用"
            )

        except Exception as e:
            self.logger.error(f"清理任务时出错: {e}", exc_info=True)
            yield event.plain_result(f"❌ 清理任务时发生错误: {str(e)}")

    @filter.command("dr.list", desc="列出所有深度研究任务")
    async def list_dr_tasks(self, event: AstrMessageEvent):
        """
        处理 /dr.list 命令，列出所有任务的概要信息。
        """
        try:
            all_tasks = []
            for task_id in list(self.task_manager.task_futures.keys()):
                task = self.task_manager.get_task_status(task_id)
                if task:
                    all_tasks.append(task)

            if not all_tasks:
                yield event.plain_result("📋 当前没有任何深度研究任务")
                return

            # 按状态分组
            status_groups = {
                "running": [],
                "completed": [],
                "failed": [],
                "pending": [],
            }
            for task in all_tasks:
                status_groups.get(task.status, status_groups["pending"]).append(task)

            result_message = "📋 深度研究任务列表\n\n"

            for status, tasks in status_groups.items():
                if not tasks:
                    continue

                status_icons = {
                    "running": "🔄",
                    "completed": "✅",
                    "failed": "❌",
                    "pending": "⏳",
                }
                result_message += f"{status_icons.get(status, '❓')} {status.upper()} ({len(tasks)}个)\n"

                for task in sorted(tasks, key=lambda x: x.created_at, reverse=True)[
                    :5
                ]:  # 最多显示5个
                    runtime = datetime.now() - task.created_at
                    runtime_str = (
                        f"{runtime.total_seconds() / 60:.0f}分钟"
                        if runtime.total_seconds() > 60
                        else f"{runtime.total_seconds():.0f}秒"
                    )
                    result_message += f"  • `{task.task_id[:8]}` - {task.user_query.core_query[:30]}{'...' if len(task.user_query.core_query) > 30 else ''} ({runtime_str})\n"

                if len(tasks) > 5:
                    result_message += f"  ... 还有 {len(tasks) - 5} 个任务\n"
                result_message += "\n"

            result_message += "💡 使用 `/dr status [任务ID]` 查看详细信息\n"
            result_message += "💡 使用 `/dr cleanup [任务ID]` 清理已完成的任务"

            yield event.plain_result(result_message)

        except Exception as e:
            self.logger.error(f"列出任务时出错: {e}", exc_info=True)
            yield event.plain_result(f"❌ 获取任务列表时发生错误: {str(e)}")

    @filter.command("dr.stats", desc="查看深度研究插件的统计信息")
    async def get_dr_stats(self, event: AstrMessageEvent):
        """
        处理 /dr.stats 命令，显示插件的统计信息和性能指标。
        """
        try:
            # 当前活跃任务统计
            active_tasks = len(
                [
                    task
                    for task in self.task_manager.task_futures.keys()
                    if self.task_manager.get_task_status(task)
                    and self.task_manager.get_task_status(task).status
                    not in ["completed", "failed"]
                ]
            )

            # 计算成功率
            total_finished = (
                self.performance_metrics["total_tasks_completed"]
                + self.performance_metrics["total_tasks_failed"]
            )
            success_rate = (
                (
                    self.performance_metrics["total_tasks_completed"]
                    / total_finished
                    * 100
                )
                if total_finished > 0
                else 0
            )

            stats_message = (
                f"📊 DeepResearch 插件统计信息\n\n"
                f"🎯 任务统计：\n"
                f"  • 已创建任务: `{self.performance_metrics['total_tasks_created']}`\n"
                f"  • 已完成任务: `{self.performance_metrics['total_tasks_completed']}`\n"
                f"  • 失败任务: `{self.performance_metrics['total_tasks_failed']}`\n"
                f"  • 当前活跃: `{active_tasks}`\n"
                f"  • 成功率: `{success_rate:.1f}%`\n\n"
                f"⏱️ 性能指标：\n"
                f"  • 平均完成时间: `{self.performance_metrics['average_completion_time']:.1f}秒`\n"
                f"  • 数据更新时间: `{datetime.fromisoformat(self.performance_metrics['last_updated']).strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
                f"💾 存储信息：\n"
                f"  • 活跃会话: `{len(self.user_active_tasks)}`\n"
                f"  • 数据目录: `{self.data_dir.name}`\n"
            )

            yield event.plain_result(stats_message)

        except Exception as e:
            self.logger.error(f"获取统计信息时出错: {e}", exc_info=True)
            yield event.plain_result(f"❌ 获取统计信息时发生错误: {str(e)}")

    @filter.command("dr.help", desc="显示深度研究插件的帮助信息")
    async def get_dr_help(self, event: AstrMessageEvent):
        """
        处理 /dr.help 命令，显示插件的详细帮助信息。
        """
        help_message = (
            "🤖 DeepResearch 深度研究插件帮助\n\n"
            "📋 可用命令：\n\n"
            "🚀 启动研究：\n"
            "  • `/deepresearch [问题]` - 启动新的深度研究任务\n"
            "  • `/dr [问题]` - 同上（简写）\n\n"
            "📊 任务管理：\n"
            "  • `/dr status [任务ID]` - 查看任务详细状态\n"
            "  • `/dr list` - 列出所有任务\n"
            "  • `/dr cleanup [任务ID]` - 清理任务记录\n\n"
            "📄 获取报告：\n"
            "  • `/dr output [任务ID]` - 获取Markdown报告\n"
            "  • `/dr output [任务ID] html` - 获取HTML报告\n"
            "  • `/dr output [任务ID] image` - 获取图片报告\n\n"
            "📈 插件信息：\n"
            "  • `/dr stats` - 查看统计信息\n"
            "  • `/dr help` - 显示此帮助信息\n\n"
            "💡 使用提示：\n"
            "  • 任务ID支持8位短格式\n"
            "  • 每个会话同时只能运行一个任务\n"
            "  • 任务状态会自动持久化保存\n"
            "  • 平均完成时间为2-5分钟\n\n"
            "🔧 版本信息：v1.919.810\n"
            "👨‍💻 作者：lxfight"
        )

        yield event.plain_result(help_message)
