import json
from pathlib import Path
from typing import Any, Optional, TypedDict


class ConfigData(TypedDict):
    AppId: str
    Secret: str
    Audit: bool
    WsKey: str
    BotName: str
    WsUrl: str
    UrlGetIframeImg: str
    UrlDefaultImg: str
    MotdOriginUrl: str
    MotdProxyUrl: str
    GenerateImgUrl: str
    TtfPath: str
    PublicGroup: list[str]
    EnableMotd: bool
    EnableAuth: bool
    EnableSensitiveFilter: bool


class ConfigManager:
    DEFAULT_BOT_NAME = "HuHoBot"
    DEFAULT_WS_URL = "ws://127.0.0.1:25671"
    DEFAULT_URL_GET_IFRAME_IMG = "http://127.0.0.1:3123/api/sync_app_img?host={SERVERHOST}&dark=true&stype={PLATFORM}&icon=https%3A%2F%2Fpic.txssb.cn%2FHuHoBot-200px.png"
    DEFAULT_URL_DEFAULT_IMG = "https://pic.txssb.cn/HuHoBot-200px.png"
    DEFAULT_MOTD_ORIGIN_URL = "motd.txssb.cn"
    DEFAULT_MOTD_PROXY_URL = "http://127.0.0.1:2087"
    DEFAULT_TTF_PATH = "MapleMono-CN-Regular.ttf"
    DEFAULT_PUBLIC_GROUP = []
    DEFAULT_ENABLE_MOTD = True
    DEFAULT_ENABLE_AUTH = True
    DEFAULT_ENABLE_SENSITIVE_FILTER = True
    DEFAULT_GENERATE_IMG_URL = "http://127.0.0.1:2087/{IMGID}.png"

    def __init__(self, config_path: Optional[str] = None):
        base_dir = Path(__file__).resolve().parent.parent
        self.config_path = Path(config_path) if config_path else base_dir / "config.json"
        self._config: Optional[ConfigData] = None

    def exists(self) -> bool:
        return self.config_path.is_file()

    @staticmethod
    def _require_string(data: dict[str, Any], field: str) -> str:
        if field not in data:
            raise ValueError(f"配置文件缺少必要字段: {field}")

        value = data[field]
        if not isinstance(value, str):
            raise ValueError(f"配置项 {field} 必须为字符串")

        value = value.strip()
        if not value:
            raise ValueError(f"配置项 {field} 不能为空")
        return value

    @staticmethod
    def _require_bool(data: dict[str, Any], field: str) -> bool:
        if field not in data:
            raise ValueError(f"配置文件缺少必要字段: {field}")

        value = data[field]
        if not isinstance(value, bool):
            raise ValueError(f"配置项 {field} 必须为布尔值")
        return value

    @staticmethod
    def _optional_string(data: dict[str, Any], field: str, default: str) -> str:
        value = data.get(field, default)
        if not isinstance(value, str):
            raise ValueError(f"配置项 {field} 必须为字符串")

        value = value.strip()
        if not value:
            raise ValueError(f"配置项 {field} 不能为空")
        return value

    @staticmethod
    def _optional_string_allow_empty(data: dict[str, Any], field: str, default: str) -> str:
        value = data.get(field, default)
        if not isinstance(value, str):
            raise ValueError(f"配置项 {field} 必须为字符串")
        return value.strip()

    @staticmethod
    def _optional_bool(data: dict[str, Any], field: str, default: bool) -> bool:
        value = data.get(field, default)
        if not isinstance(value, bool):
            raise ValueError(f"配置项 {field} 必须为布尔值")
        return value

    @staticmethod
    def _optional_string_list(data: dict[str, Any], field: str, default: list[str]) -> list[str]:
        value = data.get(field, list(default))
        if not isinstance(value, list):
            raise ValueError(f"配置项 {field} 必须为字符串列表")

        result: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"配置项 {field} 必须为字符串列表")
            item = item.strip()
            if not item:
                raise ValueError(f"配置项 {field} 不能包含空字符串")
            result.append(item)
        return result

    def validate(self, data: dict[str, Any]) -> ConfigData:
        if not isinstance(data, dict):
            raise ValueError("配置文件格式错误：根节点必须是 JSON 对象")

        return {
            "AppId": self._require_string(data, "AppId"),
            "Secret": self._require_string(data, "Secret"),
            "Audit": self._require_bool(data, "Audit"),
            "WsKey": self._require_string(data, "WsKey"),
            "BotName": self._optional_string(data, "BotName", self.DEFAULT_BOT_NAME),
            "WsUrl": self._optional_string(data, "WsUrl", self.DEFAULT_WS_URL),
            "UrlGetIframeImg": self._optional_string(data, "UrlGetIframeImg", self.DEFAULT_URL_GET_IFRAME_IMG),
            "UrlDefaultImg": self._optional_string(data, "UrlDefaultImg", self.DEFAULT_URL_DEFAULT_IMG),
            "MotdOriginUrl": self._optional_string_allow_empty(data, "MotdOriginUrl", self.DEFAULT_MOTD_ORIGIN_URL),
            "MotdProxyUrl": self._optional_string_allow_empty(data, "MotdProxyUrl", self.DEFAULT_MOTD_PROXY_URL),
            "GenerateImgUrl": self._optional_string(data, "GenerateImgUrl", self.DEFAULT_GENERATE_IMG_URL),
            "TtfPath": self._optional_string(data, "TtfPath", self.DEFAULT_TTF_PATH),
            "PublicGroup": self._optional_string_list(data, "PublicGroup", self.DEFAULT_PUBLIC_GROUP),
            "EnableMotd": self._optional_bool(data, "EnableMotd", self.DEFAULT_ENABLE_MOTD),
            "EnableAuth": self._optional_bool(data, "EnableAuth", self.DEFAULT_ENABLE_AUTH),
            "EnableSensitiveFilter": self._optional_bool(data, "EnableSensitiveFilter", self.DEFAULT_ENABLE_SENSITIVE_FILTER),
        }

    def load(self) -> ConfigData:
        with self.config_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        config = self.validate(data)
        self._config = config
        return config

    def save(
        self,
        app_id: str,
        secret: str,
        audit: bool,
        ws_key: str,
        bot_name: Optional[str] = None,
        ws_url: Optional[str] = None,
        url_get_iframe_img: Optional[str] = None,
        url_default_img: Optional[str] = None,
        motd_origin_url: Optional[str] = None,
        motd_proxy_url: Optional[str] = None,
        generate_img_url: Optional[str] = None,
        ttf_path: Optional[str] = None,
        public_group: Optional[list[str]] = None,
        enable_motd: Optional[bool] = None,
        enable_auth: Optional[bool] = None,
        enable_sensitive_filter: Optional[bool] = None,
    ) -> ConfigData:
        config = self.validate({
            "AppId": app_id,
            "Secret": secret,
            "Audit": audit,
            "WsKey": ws_key,
            "BotName": bot_name if bot_name is not None else self.DEFAULT_BOT_NAME,
            "WsUrl": ws_url if ws_url is not None else self.DEFAULT_WS_URL,
            "UrlGetIframeImg": url_get_iframe_img if url_get_iframe_img is not None else self.DEFAULT_URL_GET_IFRAME_IMG,
            "UrlDefaultImg": url_default_img if url_default_img is not None else self.DEFAULT_URL_DEFAULT_IMG,
            "MotdOriginUrl": motd_origin_url if motd_origin_url is not None else self.DEFAULT_MOTD_ORIGIN_URL,
            "MotdProxyUrl": motd_proxy_url if motd_proxy_url is not None else self.DEFAULT_MOTD_PROXY_URL,
            "GenerateImgUrl": generate_img_url if generate_img_url is not None else self.DEFAULT_GENERATE_IMG_URL,
            "TtfPath": ttf_path if ttf_path is not None else self.DEFAULT_TTF_PATH,
            "PublicGroup": public_group if public_group is not None else list(self.DEFAULT_PUBLIC_GROUP),
            "EnableMotd": enable_motd if enable_motd is not None else self.DEFAULT_ENABLE_MOTD,
            "EnableAuth": enable_auth if enable_auth is not None else self.DEFAULT_ENABLE_AUTH,
            "EnableSensitiveFilter": enable_sensitive_filter if enable_sensitive_filter is not None else self.DEFAULT_ENABLE_SENSITIVE_FILTER,
        })

        with self.config_path.open("w", encoding="utf-8") as file:
            json.dump(config, file, ensure_ascii=False, indent=2)
            file.write("\n")

        self._config = config
        return config

    def get(self, key: str, default=None):
        if self._config is None:
            self.load()
        return self._config.get(key, default)
