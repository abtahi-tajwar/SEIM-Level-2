# EVTX to JSON + Elasticsearch Search

A simple Python tool that reads Windows Event Log (`.evtx`) files, converts them to JSON, and indexes the events in Elasticsearch so you can search them from the command line or Kibana UI.

## What this tool does

1. **Parse** — reads events from an `.evtx` file using the `evtx` parser
2. **Export** — writes all events to a JSON file
3. **Index** — loads events into Elasticsearch for fast querying
4. **Search** — runs Elasticsearch `query_string` searches from the CLI

The `process` command runs JSON export and Elasticsearch indexing **in parallel** after parsing the file once.

## Project files

| File | Description |
|------|-------------|
| `evtx_tool.py` | Main script |
| `requirements.txt` | Python dependencies |
| `docker-compose.yml` | Elasticsearch + Kibana stack |
| `sample.evtx` | Sample Windows Event Log (30 events) |
| `sample.json` | Generated JSON output (created after running `process`) |

---

## Why Docker is needed

Parsing EVTX files and searching them are two separate steps.

- **EVTX → JSON** is handled entirely by Python. No Docker required.
- **Search** requires **Elasticsearch**, which is a standalone search server that must be running and reachable at `http://localhost:9200`.
- **Kibana** is Elasticsearch's web UI for exploring and querying indexed data at `http://localhost:5601`.

This project does not bundle Elasticsearch or Kibana. You need to run them yourself — locally via Docker, in the cloud, or as a manual install. Docker Compose is the quickest way to start both services together without a full manual setup.

If Elasticsearch is not running, commands like `search` will fail with connection or index errors.

---

## Prerequisites

- **Python 3.9+**
- **Docker** and **Docker Compose** (recommended, for Elasticsearch + Kibana)
- **pip**

---

## Setup

Install Python dependencies:

```bash
pip install -r requirements.txt
```

---

## Start Elasticsearch and Kibana with Docker

From the project directory, start both services:

```bash
docker compose up -d
```

This starts:

| Service | URL | Purpose |
|---------|-----|---------|
| Elasticsearch | http://localhost:9200 | Search backend used by `evtx_tool.py` |
| Kibana | http://localhost:5601 | Web UI to browse and query indexed events |

Verify Elasticsearch is up:

```bash
curl http://localhost:9200
```

You should see a JSON response with `"tagline": "You Know, for Search"`.

Open Kibana in your browser:

```
http://localhost:5601
```

Kibana may take 30–60 seconds to become ready on first startup. Check status with:

```bash
docker compose ps
```

### Stop / remove the stack (optional)

```bash
docker compose down
```

To also remove persisted Elasticsearch data:

```bash
docker compose down -v
```

If you remove the volume, you will need to re-run `process` (or let `search` auto-index) to reload events.

### Port 9200 already in use

If `docker compose up -d` fails with `Bind for 0.0.0.0:9200 failed: port is already allocated`, an old Elasticsearch container is still running (often from a previous standalone `docker run`).

Check what is using the port:

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}' | grep 9200
```

Stop and remove the conflicting container, then start the stack again:

```bash
docker stop elasticsearch
docker rm elasticsearch
docker compose up -d
```

If compose is in a bad state after the failed start:

```bash
docker compose down
docker compose up -d
```

---

## Running the application

### Step 1 — Process an EVTX file

Parse `sample.evtx`, write JSON, and index events into Elasticsearch:

```bash
python3 evtx_tool.py process sample.evtx
```

Custom output path and recreate the index:

```bash
python3 evtx_tool.py process sample.evtx -o output.json --recreate-index
```

Expected output:

```
Parsing sample.evtx ...
Parsed 30 events
Wrote 30 events to sample.json
Indexed 30 events into Elasticsearch index 'evtx-events'
```

### Step 2 — Search indexed events

**From the command line:**

```bash
python3 evtx_tool.py search "event_id:5145"
```

More examples:

```bash
python3 evtx_tool.py search "event_data.SubjectUserName:IEUser"
python3 evtx_tool.py search "channel:Security AND computer:PC01*" -n 5
```

If the Elasticsearch index does not exist yet, `search` will **auto-index** from `sample.json` (if present) or `sample.evtx`. To disable that behavior:

```bash
python3 evtx_tool.py search "event_id:5145" --no-auto-index
```

**From Kibana:**

1. Open http://localhost:5601
2. Go to **Management → Stack Management → Data Views**
3. Click **Create data view**
4. Set the name to `evtx-events` and the index pattern to `evtx-events`
5. Choose `@timestamp` as the time field, then save
6. Open **Discover**, select the `evtx-events` data view, and browse your events

You can also query in **Dev Tools** (`Management → Dev Tools`):

```json
GET evtx-events/_search
{
  "query": {
    "query_string": {
      "query": "event_id:5145"
    }
  }
}
```

---

## Search from Python

After indexing, you can also query Elasticsearch directly:

```python
from elasticsearch import Elasticsearch

es = Elasticsearch("http://localhost:9200")

response = es.search(
    index="evtx-events",
    query={"query_string": {"query": "event_id:5145"}},
)

for hit in response["hits"]["hits"]:
    print(hit["_source"])
```

---

## Configuration options

These flags work with both `process` and `search`:

| Flag | Default | Description |
|------|---------|-------------|
| `--es-url` | `http://localhost:9200` | Elasticsearch URL |
| `--index` | `evtx-events` | Elasticsearch index name |

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|--------------|-----|
| `Elasticsearch is not reachable` | Stack not running | Run `docker compose up -d` |
| Kibana shows "Unable to connect" | ES still starting | Wait ~60s, then run `docker compose ps` |
| `index_not_found_exception` | Index never created | Run `python3 evtx_tool.py process sample.evtx` |
| Empty search results | Wrong query or empty index | Re-run `process` or check your query syntax |
| Port already in use | Old container running | Run `docker compose down`, or remove any standalone `elasticsearch` container from a previous `docker run` |

---

## End-to-end quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start Elasticsearch + Kibana
docker compose up -d

# 3. Parse, export, and index
python3 evtx_tool.py process sample.evtx

# 4. Search from CLI
python3 evtx_tool.py search "event_id:5145"

# 5. Browse in Kibana
open http://localhost:5601
```
