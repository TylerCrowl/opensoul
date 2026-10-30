# OpenSoul MCP server

`opensoul/mcp_server.py` lets an agent drive a running OpenSoul app over the Model Context Protocol. Each tool is a
thin wrapper over one of the app's own HTTP routes. There is no generation logic in the server: preview mode stays
preview mode, and renders queue exactly as they do from the Storyboard.

| Tool | App route | What it does |
|---|---|---|
| `list_projects` | `GET /api/storyboard/projects` | Lists stories: id, title, lead, shot count |
| `generate_still` | `POST /api/storyboard/projects/{pid}/shots/{sid}/frame` | Makes a new start-frame still for a shot |
| `generate_shot` | `POST /api/storyboard/projects/{pid}/shots/{sid}/regenerate` | Makes a new take (`draft` or `final`); earlier takes are kept |
| `tts_line` | `POST /api/storyboard/projects/{pid}/shots/{sid}/speak` | Speaks the shot's line in the character's own voice, and returns an audio URL |
| `job_status` | `GET /api/storyboard/projects/{pid}` | Status of a take (default: the newest one) |
| `get_output` | `GET /api/storyboard/projects/{pid}` | A ready take's file path (in the data folder) plus its video and poster URLs |

### Setup tools

Six more tools set the app up for the computer it runs on ([SETUP.md](SETUP.md)). Grok Bot, a Hermes agent or you
(any MCP client) drive them the same way. Experimental: tested against the app in-process with no GPU and no network.

| Tool | App route | Changes anything? |
|---|---|---|
| `list_hardware` | `GET /api/setup/hardware` | No. GPU, memory, platform (NVIDIA / Apple / CPU), the picker's tier and any recommendation-only tier |
| `recommend_models` | `GET /api/setup/recommend` | No. The picker's recommendation plus every model slot with licence, memory, disk and source; `commercial`: `any`, `allowed` or `open_only` |
| `plan_install` | `POST /api/setup/plan` | No (saves the plan JSON). Dry run: downloads, disk, licences that need a yes, slot changes; returns a `plan_id` |
| `apply_install` | `POST /api/setup/apply` | Yes, only with the user's `approval_token` and `approve: true`. Preview mode only reports |
| `set_slot` | `POST /api/setup/slot` | Without a token: returns a plan. With the user's token and the `plan_id`: records the swap (installed models only) |
| `health_check` | `GET /api/setup/health` | No. Missing files per stage, manifest problems, free disk and memory, active slots |

Approval: there is no approve tool and no approve route. The user approves a plan on the computer itself with
`python -m opensoul.setup_engine approve <plan_id>` (add `--accept-licenses` when the plan lists licences that need a
yes), then gives the agent the one-time token, which expires after 30 minutes. An agent must never guess or make a
token. A typical run: `list_hardware` → `recommend_models` → `plan_install` → show the plan to the user → the user
approves → `apply_install` with the token and `approve: true` → `health_check`.

The Plan of Attack named these `hw_detect`, `slots_list`, `plan_setup`, `apply_plan`, `slot_set` and `health`; the
tools above are those six under the names used here. A `benchmark` tool is not built yet.

## Install and run

```bash
pip install -e ".[mcp]"          # official MCP Python SDK, mcp==2.3.0 (MIT license)
python -m opensoul.mcp_server    # stdio (default)
python -m opensoul.mcp_server --http             # streamable HTTP at http://127.0.0.1:8770/mcp
python -m opensoul.mcp_server --http --lan --host 198.51.100.20   # opens it to your LAN; only with --lan
```

- **The app.** The OpenSoul app must be running. The server talks to `OPENSOUL_URL`, which defaults to
  `http://127.0.0.1:8765`; set it with `--url` or the environment variable.
- **Binding.** HTTP listens on 127.0.0.1 only. Any other address, including `0.0.0.0`, is refused unless you pass
  `--lan`. The server has no authentication of its own, so open it to a LAN only if you trust that network.

## Grok Bot

To add an MCP server, give the command and its arguments as a stdio entry:

```json
{
  "mcpServers": {
    "opensoul": {
      "command": "python",
      "args": ["-m", "opensoul.mcp_server"],
      "cwd": "path/to/OpenSoul",
      "env": {"OPENSOUL_URL": "http://127.0.0.1:8765"}
    }
  }
}
```

If you use the HTTP transport instead, add the URL `http://127.0.0.1:8770/mcp`.

## Hermes Agent

Hermes reads `mcp_servers` from its `config.yaml`. This snippet was checked on 22 Oct 2026 against the public Hermes
Agent docs, "MCP Config Reference" and "MCP (Model Context Protocol)" at hermes-agent.nousresearch.com. The keys are
`command`, `args`, `env` and `cwd` for stdio, and `url` for HTTP.

```yaml
mcp_servers:
  opensoul:
    command: "python"
    args: ["-m", "opensoul.mcp_server"]
    cwd: "path/to/OpenSoul"
    env:
      OPENSOUL_URL: "http://127.0.0.1:8765"
    timeout: 300          # a final take can take minutes; poll job_status instead of waiting

  # or, with `python -m opensoul.mcp_server --http` running:
  # opensoul_http:
  #   url: "http://127.0.0.1:8770/mcp"
```

## Tests

`tests/test_mcp_server.py` covers the job tools against a mocked backend, and `tests/test_mcp_setup_tools.py` runs
the setup tools against the app in-process (preview mode, a temp data folder), with no GPU and no network:

- the tool list
- the route each tool calls
- error messages passed through as tool errors
- the loopback-only bind rule
