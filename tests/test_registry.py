import pytest
from tools.registry import Permission, Tool, ToolRegistry


class FakeReadTool(Tool):
    @property
    def name(self) -> str: return "fake_read"
    @property
    def description(self) -> str: return "A read-only fake tool"
    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}
    @property
    def permission(self) -> Permission: return Permission.READ_ONLY
    def execute(self, **kwargs) -> str: return "read result"


class FakeWriteTool(Tool):
    @property
    def name(self) -> str: return "fake_write"
    @property
    def description(self) -> str: return "A write fake tool"
    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}
    @property
    def permission(self) -> Permission: return Permission.WRITE
    def execute(self, **kwargs) -> str: return "write result"


class FakeDangerousTool(Tool):
    @property
    def name(self) -> str: return "fake_dangerous"
    @property
    def description(self) -> str: return "Dangerous tool"
    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}
    @property
    def permission(self) -> Permission: return Permission.DANGEROUS
    def execute(self, **kwargs) -> str: return "danger!"


class FakeConfirmTool(Tool):
    @property
    def name(self) -> str: return "fake_confirm"
    @property
    def description(self) -> str: return "Confirmation tool"
    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}
    @property
    def permission(self) -> Permission: return Permission.REQUIRES_CONFIRMATION
    def execute(self, **kwargs) -> str: return "confirmed"


def make_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(FakeReadTool())
    r.register(FakeWriteTool())
    r.register(FakeDangerousTool())
    r.register(FakeConfirmTool())
    return r


def test_read_only_ceiling_returns_only_read():
    r = make_registry()
    tools = r.get_tools(max_permission=Permission.READ_ONLY)
    names = [t.name for t in tools]
    assert "fake_read" in names
    assert "fake_write" not in names
    assert "fake_dangerous" not in names
    assert "fake_confirm" not in names


def test_write_ceiling_includes_read_and_write():
    r = make_registry()
    tools = r.get_tools(max_permission=Permission.WRITE)
    names = [t.name for t in tools]
    assert "fake_read" in names
    assert "fake_write" in names
    assert "fake_dangerous" not in names


def test_include_dangerous_adds_both_dangerous_tiers():
    r = make_registry()
    tools = r.get_tools(max_permission=Permission.WRITE, include_dangerous=True)
    names = [t.name for t in tools]
    assert "fake_dangerous" in names
    assert "fake_confirm" in names


def test_duplicate_registration_raises():
    r = ToolRegistry()
    r.register(FakeReadTool())
    with pytest.raises(ValueError, match="already registered"):
        r.register(FakeReadTool())


def test_len_matches_registered_count():
    r = make_registry()
    assert len(r) == 4


def test_to_api_dict_has_required_keys():
    tool = FakeReadTool()
    api = tool.to_api_dict()
    assert api["name"] == "fake_read"
    assert "description" in api
    assert "input_schema" in api


def test_get_tools_invalid_ceiling_raises():
    r = make_registry()
    with pytest.raises(ValueError, match="not a valid ceiling permission"):
        r.get_tools(max_permission=Permission.DANGEROUS)


def test_get_by_name_miss_returns_none():
    r = make_registry()
    assert r.get_by_name("nonexistent") is None


def test_get_tools_empty_registry_returns_empty_list():
    r = ToolRegistry()
    assert r.get_tools(max_permission=Permission.WRITE) == []
