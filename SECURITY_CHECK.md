# Security check (OSV)

Plan §9.1 record. Covers the backend lock file only. The npm side (`npm audit` on `frontend/package-lock.json`) is T1.11 and is not in this file yet.

## Run

- Date: 2026-10-16
- Command: `python3 -I scripts/check_vulns.py backend/uv.lock`
- Source: `https://api.osv.dev/v1/query` (POST, per package name, ecosystem and version)
- Ecosystem: PyPI
- Exit code: 0

## Result

- Checked: 91 package versions
- With advisories: 0

## Package table

```
ECOSYSTEM  PACKAGE                                   VERSION    ADVISORIES  IDS
---------  ----------------------------------------  ---------  ----------  ---
PyPI       annotated-doc                             0.0.5      0           -
PyPI       annotated-types                           0.8.0      0           -
PyPI       anyio                                     4.15.1     0           -
PyPI       ast-serialize                             0.13.0     0           -
PyPI       backoff                                   2.2.1      0           -
PyPI       certifi                                   2026.7.22  0           -
PyPI       charset-normalizer                        3.5.2      0           -
PyPI       click                                     8.5.0      0           -
PyPI       colorama                                  0.4.6      0           -
PyPI       distro                                    1.9.0      0           -
PyPI       fastapi                                   0.143.2    0           -
PyPI       googleapis-common-protos                  1.75.5     0           -
PyPI       graphiti-core                             0.31.1     0           -
PyPI       h11                                       0.16.0     0           -
PyPI       httpcore                                  1.0.9      0           -
PyPI       httpcore2                                 2.13.1     0           -
PyPI       httptools                                 0.9.0      0           -
PyPI       httpx                                     0.28.1     0           -
PyPI       httpx2                                    2.13.1     0           -
PyPI       httpx2-jsfetch                            1.0        0           -
PyPI       idna                                      3.20       0           -
PyPI       iniconfig                                 2.3.1      0           -
PyPI       jiter                                     0.17.0     0           -
PyPI       jsonpatch                                 1.35       0           -
PyPI       jsonpointer                               3.2.1      0           -
PyPI       langchain-core                            1.6.11     0           -
PyPI       langchain-openai                          1.7.2      0           -
PyPI       langchain-protocol                        0.0.19     0           -
PyPI       langfuse                                  5.0.1      0           -
PyPI       langgraph                                 1.2.15     0           -
PyPI       langgraph-checkpoint                      4.3.0      0           -
PyPI       langgraph-prebuilt                        1.1.1      0           -
PyPI       langgraph-sdk                             0.4.7      0           -
PyPI       langsmith                                 0.14.9     0           -
PyPI       librt                                     0.16.0     0           -
PyPI       lxml                                      6.1.3      0           -
PyPI       mypy                                      2.4.0      0           -
PyPI       mypy-extensions                           1.1.0      0           -
PyPI       neo4j                                     6.4.1      0           -
PyPI       numpy                                     2.5.4      0           -
PyPI       openai                                    3.31.0     0           -
PyPI       opentelemetry-api                         1.45.1     0           -
PyPI       opentelemetry-exporter-http-transport     0.66b1     0           -
PyPI       opentelemetry-exporter-otlp-common        0.66b1     0           -
PyPI       opentelemetry-exporter-otlp-proto-common  1.45.1     0           -
PyPI       opentelemetry-exporter-otlp-proto-http    1.45.1     0           -
PyPI       opentelemetry-proto                       1.45.1     0           -
PyPI       opentelemetry-sdk                         1.45.1     0           -
PyPI       opentelemetry-semantic-conventions        0.66b1     0           -
PyPI       orjson                                    3.13.0     0           -
PyPI       ormsgpack                                 1.13.0     0           -
PyPI       packaging                                 26.3       0           -
PyPI       pathspec                                  1.1.1      0           -
PyPI       pluggy                                    1.7.0      0           -
PyPI       posthog                                   7.70.2     0           -
PyPI       protobuf                                  7.36.2     0           -
PyPI       pydantic                                  2.14.1     0           -
PyPI       pydantic-core                             2.50.1     0           -
PyPI       pydantic-settings                         2.16.0     0           -
PyPI       pygments                                  2.21.0     0           -
PyPI       pymysql                                   1.2.3      0           -
PyPI       pypdf                                     6.20.1     0           -
PyPI       pytest                                    9.1.1      0           -
PyPI       pytest-asyncio                            1.4.0      0           -
PyPI       python-docx                               1.2.0      0           -
PyPI       python-dotenv                             1.2.4      0           -
PyPI       python-multipart                          0.0.32     0           -
PyPI       pytz                                      2026.5     0           -
PyPI       pyyaml                                    6.0.3      0           -
PyPI       regex                                     2026.9.29  0           -
PyPI       requests                                  2.34.2     0           -
PyPI       requests-toolbelt                         1.0.0      0           -
PyPI       ruff                                      0.17.1     0           -
PyPI       sniffio                                   1.3.1      0           -
PyPI       sqlalchemy                                2.1.4      0           -
PyPI       sse-starlette                             3.5.0      0           -
PyPI       starlette                                 1.8.0      0           -
PyPI       tenacity                                  9.2.1      0           -
PyPI       tiktoken                                  0.14.0     0           -
PyPI       truststore                                0.10.5     0           -
PyPI       typing-extensions                         4.16.0     0           -
PyPI       typing-inspection                         0.4.4      0           -
PyPI       urllib3                                   2.8.0      0           -
PyPI       uuid-utils                                0.17.1     0           -
PyPI       uvicorn                                   0.54.0     0           -
PyPI       uvloop                                    0.23.0     0           -
PyPI       watchfiles                                1.3.0      0           -
PyPI       websockets                                16.1.1     0           -
PyPI       wrapt                                     2.5.1      0           -
PyPI       xxhash                                    4.0.1      0           -
PyPI       zstandard                                 0.25.0     0           -
```

checked 91 package versions, 0 with advisories

## Findings

None. Every listed version has 0 advisories, so no version change is needed.

## Re-run

Run the same command from the repo root to reproduce this result. The table above is the full output.
