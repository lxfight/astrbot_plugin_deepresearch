# 这里存储 astrbot_plugin_deepresearch 插件的常量

# 读取metadata.yaml文件内容来同步插件信息常量
import yaml
import os

# 获取当前文件的目录
CURRENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 读取metadata.yaml文件
with open(os.path.join(CURRENT_DIR, "metadata.yaml"), "r", encoding="utf-8") as file:
    metadata = yaml.safe_load(file)

PLUGIN_NAME = metadata.get("name", "astrbot_plugin_deepresearch")
PLUGIN_AUTHOR = metadata.get("author", "lxfight")
PLUGIN_DESCRIPTION = metadata.get("description", "Astrbot Deep Research Plugin")
PLUGIN_VERSION = metadata.get("version", "0.1.0")
PLUGIN_REPO = metadata.get(
    "repo", "https://github.com/lxfight/astrbot_plugin_deepresearch"
)

REQUEST_TIMEOUT_SECONDS = 30
