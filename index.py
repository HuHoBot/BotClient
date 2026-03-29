import sys
import json
import asyncio
import argparse
from ymbotpy import logging as botpy_logging

# 本地模块导入
import libs.main as BotMain
import libs.audit as BotAudit
from libs.basic import init_db
from libs.configManager import ConfigManager

_log = botpy_logging.get_logger()


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='QQ机器人启动程序')
    parser.add_argument('--webhook', action='store_true', help='启用Webhook模式')
    parser.add_argument('--sandbox', action='store_true', help='强制启用沙箱模式')
    return parser.parse_args()


async def run_main(app_id: str, secret: str, ws_key: str, bot_name: str, ws_url: str, sandbox: bool, webhook: bool):
    """主运行逻辑"""
    try:
        if webhook:
            _log.info("以Webhook模式启动...")
        else:
            _log.info("以Websocket模式启动...")
        await BotMain.main(app_id, secret, ws_key, bot_name, ws_url, sandbox, webhook)
    except KeyboardInterrupt:
        _log.info("程序已手动终止")
    except Exception as e:
        _log.error(f"运行时发生严重错误: {str(e)}")
        sys.exit(1)


def interactive_setup(config_manager: ConfigManager):
    """交互式配置向导"""
    print("\n== 首次配置向导 ==")
    app_id = input("请输入AppID(机器人ID): ").strip()
    secret = input("请输入AppSecret(机器人密钥): ").strip()
    ws_key = input("请输入WebSocketKey(主控密钥): ").strip()

    while True:
        audit = input("机器人是否已通过审核？(y/n): ").strip().lower()
        if audit in ('y', 'n'):
            config_manager.save(app_id, secret, audit == 'y', ws_key)
            return
        print("请输入 y 或 n")


if __name__ == '__main__':
    args = parse_args()
    config_manager = ConfigManager()

    if not config_manager.exists():
        interactive_setup(config_manager)
        sys.exit("请重新启动程序以应用配置")

    try:
        config = config_manager.load()
    except json.JSONDecodeError as e:
        _log.error(f"配置文件不是合法的 JSON: {str(e)}")
        sys.exit("配置文件加载失败，请检查config.json格式")
    except ValueError as e:
        _log.error(str(e))
        sys.exit("配置文件加载失败，请检查config.json内容")
    except OSError as e:
        _log.error(f"配置文件读取失败: {str(e)}")
        sys.exit("配置文件读取失败，请检查config.json")

    try:
        asyncio.run(init_db())
    except Exception as e:
        _log.error(f"数据库初始化失败: {str(e)}")
        sys.exit("数据库初始化失败，请检查data目录和数据库权限")

    if config['Audit'] or args.sandbox:
        sandbox = args.sandbox if args.sandbox else False
        asyncio.run(run_main(
            config['AppId'],
            config['Secret'],
            config['WsKey'],
            config['BotName'],
            config['WsUrl'],
            sandbox,
            args.webhook
        ))
    else:
        BotAudit.main(config['AppId'], config['Secret'])
