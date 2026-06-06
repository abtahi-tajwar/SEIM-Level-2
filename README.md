# EVTX to JSON + Elasticsearch Search

A simple Python tool that reads Windows Event Log (`.evtx`) files, converts them to JSON, and indexes the events in Elasticsearch so you can search them from the command line.

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
| `sample.evtx` | Sample Windows Event Log (30 events) |
| `sample.json` | Generated JSON output (created after running `process`) |

---

## Why Docker is needed

Parsing EVTX files and searching them are two separate steps.

- **EVTX → JSON** is handled entirely by Python. No Docker required.
- **Search** requires **Elasticsearch**, which is a standalone search server that must be running and reachable at `http://localhost:9200`.

This project does not bundle Elasticsearch. You need to run it yourself — locally, in the cloud, or via Docker. Docker is the quickest way to get a local Elasticsearch instance without a full manual install.

If Elasticsearch is not running, commands like `search` will fail with connection or index errors.

---

## Prerequisites

- **Python 3.9+**
- **Docker** (recommended, for running Elasticsearch locally)
- **pip**

---

## Setup

Install Python dependencies:

```bash
pip install -r requirements.txt
```

---

## Start Elasticsearch with Docker

Run this once before indexing or searching:

```bash
docker run -d \
  --name elasticsearch \
  -p 9200:9200 \
  -e discovery.type=single-node \
  -e xpack.security.enabled=false \
  docker.elastic.co/elasticsearch/elasticsearch:8.13.4
```

Verify Elasticsearch is up:

```bash
curl http://localhost:9200
```

You should see a JSON response with `"tagline": "You Know, for Search"`.

### Stop / remove the container (optional)

```bash
docker stop elasticsearch
docker rm elasticsearch
```

Data is stored inside the container. If you remove it, you will need to re-run `process` (or let `search` auto-index) to reload events.

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
| `Elasticsearch is not reachable` | ES not running | Start the Docker container (see above) |
| `index_not_found_exception` | Index never created | Run `python3 evtx_tool.py process sample.evtx` |
| Empty search results | Wrong query or empty index | Re-run `process` or check your query syntax |

---

## End-to-end quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start Elasticsearch
docker run -d --name elasticsearch -p 9200:9200 \
  -e discovery.type=single-node \
  -e xpack.security.enabled=false \
  docker.elastic.co/elasticsearch/elasticsearch:8.13.4

# 3. Parse, export, and index
python3 evtx_tool.py process sample.evtx

# 4. Search
python3 evtx_tool.py search "event_id:5145"
```
