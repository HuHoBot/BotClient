import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Union


PLACEHOLDER_PATTERN = re.compile(r"\{\{\.([A-Za-z_][A-Za-z0-9_]*)\}\}")


class MarkdownTemplate:
    """单个 Markdown 模板文件。"""

    def __init__(self, path: Path):
        self.path = path
        self.name = path.stem

    def _load(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @staticmethod
    def _value_to_text(value: Any) -> str:
        if isinstance(value, (list, tuple)):
            return str(value[0]) if value else ""
        return str(value)

    @classmethod
    def _params_to_dict(cls, params: Iterable[Any]) -> dict[str, str]:
        data: dict[str, str] = {}
        for item in params:
            if isinstance(item, Mapping):
                key = item.get("key")
                values = item.get("values", [])
            else:
                key = getattr(item, "key", None)
                values = getattr(item, "values", [])

            if key is None:
                continue
            data[str(key)] = cls._value_to_text(values)
        return data

    @classmethod
    def _normalize_data(cls, data: Any) -> dict[str, str]:
        if data is None:
            return {}

        if isinstance(data, Mapping):
            params = data.get("params")
            if params is not None:
                return cls._params_to_dict(params)
            return {str(key): cls._value_to_text(value) for key, value in data.items()}

        return cls._params_to_dict(data)

    @classmethod
    def render_content(cls, content: str, data: Any) -> str:
        """使用 data 替换指定 Markdown 内容中的 {{.placeholder}}。"""
        normalized_data = cls._normalize_data(data)

        def replace_placeholder(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in normalized_data:
                return match.group(0)
            return normalized_data[key]

        return PLACEHOLDER_PATTERN.sub(replace_placeholder, content)

    RenderContent = render_content

    def get(self, data: Any) -> str:
        """使用 data 替换模板中的 {{.placeholder}} 并返回渲染后的字符串。"""
        return self.render_content(self._load(), data)

    Get = get


class MarkdownManager:
    """管理 mdTemplate 目录下的 Markdown 模板。"""

    def __init__(self, base_dir: Optional[Union[str, Path]] = None):
        project_dir = Path(__file__).resolve().parent.parent
        self.base_dir = Path(base_dir) if base_dir else project_dir / "mdTemplate"
        self._templates: dict[str, MarkdownTemplate] = {}
        self.reload()

    def reload(self):
        """重新扫描模板目录，并按文件名注册模板属性。"""
        self._templates.clear()
        if not self.base_dir.is_dir():
            return

        for path in self.base_dir.glob("*.md"):
            template = MarkdownTemplate(path)
            self._templates[template.name] = template
            setattr(self, template.name, template)

    def get_template(self, name: str) -> MarkdownTemplate:
        """按模板文件名获取模板对象，name 不需要包含 .md 后缀。"""
        template_name = Path(name).stem
        if template_name not in self._templates:
            raise KeyError(f"Markdown模板不存在: {template_name}")
        return self._templates[template_name]

    GetTemplate = get_template

    def render(self, content: str, data: Any) -> str:
        """替换自定义 Markdown 内容中的 {{.placeholder}}。"""
        return MarkdownTemplate.render_content(content, data)

    Render = render


mdManager = MarkdownManager()


__all__ = [
    "MarkdownManager",
    "MarkdownTemplate",
    "mdManager",
]

