#!/usr/bin/env python3
"""Parse Windows EVTX logs to JSON and index them in Elasticsearch."""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

from elasticsearch import Elasticsearch, NotFoundError, helpers
from evtx import PyEvtxParser


DEFAULT_EVTX = Path(__file__).resolve().parent / "sample.evtx"
DEFAULT_JSON = Path(__file__).resolve().parent / "sample.json"
DEFAULT_INDEX = "evtx-events"
DEFAULT_ES_URL = "http://localhost:9200"


def _attr(value: Any, key: str = "Name") -> Any:
    if isinstance(value, dict):
        attrs = value.get("#attributes")
        if isinstance(attrs, dict) and key in attrs:
            return attrs[key]
        return value.get(key, value)
    return value


def _normalize_timestamp(record: dict[str, Any]) -> str:
    payload = json.loads(record["data"])
    system = payload.get("Event", {}).get("System", {})
    time_created = system.get("TimeCreated")
    if isinstance(time_created, dict):
        system_time = time_created.get("#attributes", {}).get("SystemTime")
        if system_time:
            return system_time

    raw = record["timestamp"]
    # PyEvtxParser returns "YYYY-MM-DD HH:MM:SS.ffffff UTC" — convert to ISO-8601.
    if isinstance(raw, str) and raw.endswith(" UTC"):
        return raw[:-4].replace(" ", "T") + "Z"
    return raw


def parse_evtx(evtx_path: Path) -> list[dict[str, Any]]:
    parser = PyEvtxParser(str(evtx_path))
    documents: list[dict[str, Any]] = []

    for record in parser.records_json():
        payload = json.loads(record["data"])
        event = payload.get("Event", {})
        system = event.get("System", {})
        event_data = event.get("EventData") or {}

        documents.append(
            {
                "event_record_id": record["event_record_id"],
                "@timestamp": _normalize_timestamp(record),
                "event_id": system.get("EventID"),
                "level": system.get("Level"),
                "channel": system.get("Channel"),
                "computer": system.get("Computer"),
                "provider": _attr(system.get("Provider")),
                "event_data": event_data,
                "raw_event": event,
            }
        )

    return documents


def export_json(documents: list[dict[str, Any]], json_path: Path) -> int:
    json_path.write_text(json.dumps(documents, indent=2), encoding="utf-8")
    return len(documents)


def index_elasticsearch(
    documents: list[dict[str, Any]],
    es_url: str,
    index_name: str,
    recreate: bool = False,
) -> int:
    es = Elasticsearch(es_url)

    if not es.ping():
        raise ConnectionError(f"Elasticsearch is not reachable at {es_url}")

    if recreate and es.indices.exists(index=index_name):
        es.indices.delete(index=index_name)

    if not es.indices.exists(index=index_name):
        es.indices.create(
            index=index_name,
            mappings={
                "properties": {
                    "@timestamp": {"type": "date"},
                    "event_id": {"type": "long"},
                    "level": {"type": "long"},
                    "channel": {"type": "keyword"},
                    "computer": {"type": "keyword"},
                    "provider": {"type": "keyword"},
                    "event_data": {"type": "object", "enabled": True},
                    "raw_event": {"type": "object", "enabled": False},
                }
            },
        )

    actions = (
        {"_index": index_name, "_source": doc}
        for doc in documents
    )
    success, _ = helpers.bulk(es, actions, raise_on_error=True)
    es.indices.refresh(index=index_name)
    return success


def process_evtx(
    evtx_path: Path,
    json_path: Path,
    es_url: str,
    index_name: str,
    recreate_index: bool = False,
) -> None:
    print(f"Parsing {evtx_path} ...")
    documents = parse_evtx(evtx_path)
    print(f"Parsed {len(documents)} events")

    results: dict[str, Any] = {}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(export_json, documents, json_path): "json",
            executor.submit(
                index_elasticsearch,
                documents,
                es_url,
                index_name,
                recreate_index,
            ): "elasticsearch",
        }

        for future in as_completed(futures):
            task = futures[future]
            try:
                count = future.result()
                results[task] = count
            except Exception as exc:
                results[task] = exc

    json_result = results.get("json")
    es_result = results.get("elasticsearch")

    if isinstance(json_result, int):
        print(f"Wrote {json_result} events to {json_path}")
    else:
        print(f"JSON export failed: {json_result}", file=sys.stderr)

    if isinstance(es_result, int):
        print(f"Indexed {es_result} events into Elasticsearch index '{index_name}'")
    else:
        print(f"Elasticsearch indexing failed: {es_result}", file=sys.stderr)

    if not isinstance(json_result, int) and not isinstance(es_result, int):
        raise SystemExit(1)


def get_es_client(es_url: str) -> Elasticsearch:
    es = Elasticsearch(es_url)
    if not es.ping():
        raise ConnectionError(
            f"Elasticsearch is not reachable at {es_url}. "
            "Start it first, e.g.:\n"
            "  docker run -d --name elasticsearch -p 9200:9200 "
            "-e discovery.type=single-node -e xpack.security.enabled=false "
            "docker.elastic.co/elasticsearch/elasticsearch:8.13.4"
        )
    return es


def load_documents(evtx_path: Path, json_path: Path) -> list[dict[str, Any]]:
    if json_path.is_file():
        return json.loads(json_path.read_text(encoding="utf-8"))
    if evtx_path.is_file():
        return parse_evtx(evtx_path)
    raise FileNotFoundError(
        f"No indexed data source found. Run:\n"
        f"  python3 evtx_tool.py process {DEFAULT_EVTX.name}"
    )


def ensure_index(
    es: Elasticsearch,
    es_url: str,
    index_name: str,
    evtx_path: Path,
    json_path: Path,
    auto_index: bool,
) -> None:
    if es.indices.exists(index=index_name) and es.count(index=index_name)["count"] > 0:
        return

    if not auto_index:
        raise SystemExit(
            f"Index '{index_name}' does not exist or is empty.\n"
            f"Index your EVTX file first:\n"
            f"  python3 evtx_tool.py process {evtx_path}"
        )

    source = json_path if json_path.is_file() else evtx_path
    print(f"Index '{index_name}' not found — indexing from {source.name} ...")
    documents = load_documents(evtx_path, json_path)
    count = index_elasticsearch(documents, es_url, index_name)
    print(f"Indexed {count} events into '{index_name}'")


def search_events(
    query: str,
    es_url: str,
    index_name: str,
    size: int = 10,
    evtx_path: Path = DEFAULT_EVTX,
    json_path: Path = DEFAULT_JSON,
    auto_index: bool = True,
) -> list[dict[str, Any]]:
    es = get_es_client(es_url)
    ensure_index(es, es_url, index_name, evtx_path, json_path, auto_index)

    try:
        response = es.search(
            index=index_name,
            query={"query_string": {"query": query}},
            size=size,
            sort=[{"@timestamp": {"order": "desc"}}],
        )
    except NotFoundError as exc:
        raise SystemExit(
            f"Index '{index_name}' not found.\n"
            f"Run: python3 evtx_tool.py process {evtx_path}"
        ) from exc

    return [hit["_source"] for hit in response["hits"]["hits"]]


def print_search_results(results: list[dict[str, Any]]) -> None:
    if not results:
        print("No matches.")
        return

    for idx, doc in enumerate(results, start=1):
        print(f"\n--- Result {idx} ---")
        print(f"timestamp: {doc.get('@timestamp')}")
        print(f"event_id:  {doc.get('event_id')}")
        print(f"computer:  {doc.get('computer')}")
        print(f"provider:  {doc.get('provider')}")
        print(f"channel:   {doc.get('channel')}")
        if doc.get("event_data"):
            print("event_data:")
            for key, value in doc["event_data"].items():
                print(f"  {key}: {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert EVTX to JSON and index events in Elasticsearch."
    )
    parser.add_argument(
        "--es-url",
        default=DEFAULT_ES_URL,
        help=f"Elasticsearch URL (default: {DEFAULT_ES_URL})",
    )
    parser.add_argument(
        "--index",
        default=DEFAULT_INDEX,
        help=f"Elasticsearch index name (default: {DEFAULT_INDEX})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    process_parser = subparsers.add_parser(
        "process",
        help="Parse EVTX, write JSON, and index to Elasticsearch in parallel",
    )
    process_parser.add_argument(
        "evtx",
        nargs="?",
        default=str(DEFAULT_EVTX),
        help=f"Path to .evtx file (default: {DEFAULT_EVTX.name})",
    )
    process_parser.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_JSON),
        help=f"JSON output path (default: {DEFAULT_JSON.name})",
    )
    process_parser.add_argument(
        "--recreate-index",
        action="store_true",
        help="Delete and recreate the Elasticsearch index before indexing",
    )

    search_parser = subparsers.add_parser(
        "search",
        help='Search indexed events, e.g. search "event_id:5145 AND computer:PC01*"',
    )
    search_parser.add_argument("query", help="Elasticsearch query_string query")
    search_parser.add_argument(
        "-n",
        "--size",
        type=int,
        default=10,
        help="Maximum number of results (default: 10)",
    )
    search_parser.add_argument(
        "--evtx",
        default=str(DEFAULT_EVTX),
        help=f"EVTX file to index if missing (default: {DEFAULT_EVTX.name})",
    )
    search_parser.add_argument(
        "--json",
        default=str(DEFAULT_JSON),
        help=f"JSON file to index if missing and present (default: {DEFAULT_JSON.name})",
    )
    search_parser.add_argument(
        "--no-auto-index",
        action="store_true",
        help="Do not auto-index when the Elasticsearch index is missing",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "process":
        process_evtx(
            evtx_path=Path(args.evtx),
            json_path=Path(args.output),
            es_url=args.es_url,
            index_name=args.index,
            recreate_index=args.recreate_index,
        )
        return

    if args.command == "search":
        results = search_events(
            query=args.query,
            es_url=args.es_url,
            index_name=args.index,
            size=args.size,
            evtx_path=Path(args.evtx),
            json_path=Path(args.json),
            auto_index=not args.no_auto_index,
        )
        print_search_results(results)
        return

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
