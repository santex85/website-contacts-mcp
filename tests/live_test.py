"""Live smoke test against real websites. Run: .venv/bin/python tests/live_test.py"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import server  # noqa: E402


def show(name, r, ok):
    s = json.dumps(r, ensure_ascii=False, default=str)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {len(s)} bytes | {s[:600]}\n")
    return bool(ok)


async def main():
    res = []
    tools = await server.mcp.list_tools()
    res.append(show("list_tools", [t.name for t in tools], len(tools) == 2))
    r = await server.get_website_contacts("apify.com")
    res.append(show("get_website_contacts", r, not r["error"] and "hello@apify.com" in r["emails"] and r["linkedin"]))
    rows = await server.get_websites_contacts(["https://www.python.org", "https://www.debian.org", "not a url"], max_pages=2)
    res.append(show("get_websites_contacts", rows, len(rows) == 3 and rows[0]["emails"] and rows[2]["error"]))
    print(f"{sum(res)}/{len(res)} passed")
    sys.exit(0 if all(res) else 1)


asyncio.run(main())
