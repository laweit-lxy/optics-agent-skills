"""The MCP server over a real stdio connection, as an MCP client would use it."""
from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

from conftest import REPO, SAMPLES, sample_reference, sample_zmx

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from optics_agent_skills import engines  # noqa: E402

TOOLS = {"list_samples", "analyze_prescription", "cross_check_prescription", "diagnose_discrepancies",
         "wave_optics_self_test", "server_info"}


def engines_available(*names: str) -> bool:
    try:
        for name in names:
            engines.interpreter(name)
    except engines.EngineError:
        return False
    return True


def call(tmp_path, tool: str, arguments: dict | None = None):
    async def session():
        env = dict(os.environ, OPTICS_SKILLS_OUTPUT_ROOT=str(tmp_path), PYTHONPATH=str(REPO / "src"))
        params = StdioServerParameters(command=sys.executable, args=["-m", "optics_agent_skills", "serve"],
                                       env=env, cwd=str(tmp_path))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = await client.list_tools()
                result = await client.call_tool(tool, arguments or {})
                return {t.name for t in tools.tools}, result
    return asyncio.run(session())


def payload(result) -> object:
    if result.structured_content is not None:
        content = result.structured_content
        return content.get("result", content) if set(content) == {"result"} else content
    return json.loads(result.content[0].text)


def test_tools_are_listed_and_samples_resolve(tmp_path):
    names, result = call(tmp_path, "list_samples")
    assert names == TOOLS
    assert not result.is_error
    samples = payload(result)
    assert [s["name"] for s in samples] == sorted(SAMPLES)
    for sample in samples:
        assert os.path.isfile(sample["zmx"]) and os.path.isfile(sample["opticstudio_reference"])


def test_relative_path_is_a_tool_error(tmp_path):
    _, result = call(tmp_path, "diagnose_discrepancies", {"zmx_path": "cooke.zmx"})
    assert result.is_error
    assert "absolute" in result.content[0].text


@pytest.mark.skipif(not engines_available("design", "crosscheck"),
                    reason="needs the design-optical-systems and cross-check-optical-designs environments")
def test_diagnose_cooke_over_mcp(tmp_path):
    _, result = call(tmp_path, "diagnose_discrepancies",
                     {"zmx_path": str(sample_zmx("cooke")), "reference_json_path": str(sample_reference("cooke"))})
    assert not result.is_error, result.content
    report = payload(result)
    causes = {c["category"]: c["confirmed_by"] for c in report["causes"]}
    assert causes["material_catalog"] == "material_catalog_swap"
    assert report["reference"]["rayoptics"]["agrees"] is True
    assert os.path.isfile(report["report_path"])
