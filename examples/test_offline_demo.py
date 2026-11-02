from __future__ import annotations

from offline_demo import main


def test_offline_demo_runs_against_mocks(capsys) -> None:
    run = main()
    printed = capsys.readouterr().out

    paths = [path for path, _ in run["api_calls"]]
    assert paths == ["/v2/query", "/v2/query"]  # middleware recall, then the agent's own bhived_query call
    assert "## Shared lessons (from bhived)" in printed
    assert "pydantic 2: use model_config" in printed
    assert "from_attributes" in run["result"]["messages"][-1].content
