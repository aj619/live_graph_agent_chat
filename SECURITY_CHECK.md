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

## npm / frontend check

### Run

- Date: 2026-10-16
- Command 1: `python3 -I scripts/check_vulns.py frontend/package-lock.json`
- Command 2: `npm audit` run from `frontend/` (read-only; no `npm audit fix`, no install)
- npm version: 11.19.0
- Source: `https://api.osv.dev/v1/query` (POST, per package name, ecosystem and version)
- Ecosystem: npm
- Exit code (OSV script): 0
- Exit code (npm audit): 0
- `frontend/package.json` and `frontend/package-lock.json` checksums unchanged after the run

### Result

- OSV script: checked 256 package versions, 0 with advisories
- npm audit: found 0 vulnerabilities (info 0, low 0, moderate 0, high 0, critical 0, total 0)
- npm audit dependency counts: prod 7, dev 250, optional 27, peer 10, total 256

### Package table (OSV script)

```
ECOSYSTEM  PACKAGE                                VERSION  ADVISORIES  IDS
---------  -------------------------------------  -------  ----------  ---
npm        @adobe/css-tools                       4.5.0    0           -
npm        @asamuzakjp/css-color                  3.2.0    0           -
npm        @babel/code-frame                      7.29.7   0           -
npm        @babel/helper-validator-identifier     7.29.7   0           -
npm        @babel/runtime                         7.29.10  0           -
npm        @csstools/color-helpers                5.1.0    0           -
npm        @csstools/css-calc                     2.1.4    0           -
npm        @csstools/css-color-parser             3.1.0    0           -
npm        @csstools/css-parser-algorithms        3.0.5    0           -
npm        @csstools/css-tokenizer                3.0.4    0           -
npm        @eslint-community/eslint-utils         4.10.1   0           -
npm        @eslint-community/regexpp              4.12.2   0           -
npm        @eslint/config-array                   0.21.2   0           -
npm        @eslint/config-helpers                 0.4.2    0           -
npm        @eslint/core                           0.17.0   0           -
npm        @eslint/eslintrc                       3.3.7    0           -
npm        @eslint/js                             9.39.5   0           -
npm        @eslint/object-schema                  2.1.7    0           -
npm        @eslint/plugin-kit                     0.4.1    0           -
npm        @humanfs/core                          0.19.2   0           -
npm        @humanfs/node                          0.16.8   0           -
npm        @humanfs/types                         0.15.0   0           -
npm        @humanwhocodes/module-importer         1.0.1    0           -
npm        @humanwhocodes/retry                   0.4.3    0           -
npm        @jridgewell/resolve-uri                3.1.2    0           -
npm        @jridgewell/sourcemap-codec            1.6.0    0           -
npm        @jridgewell/trace-mapping              0.3.31   0           -
npm        @oxc-project/types                     0.154.0  0           -
npm        @rolldown/binding-android-arm-eabi     1.2.14   0           -
npm        @rolldown/binding-android-arm64        1.2.14   0           -
npm        @rolldown/binding-darwin-arm64         1.2.14   0           -
npm        @rolldown/binding-darwin-x64           1.2.14   0           -
npm        @rolldown/binding-freebsd-x64          1.2.14   0           -
npm        @rolldown/binding-linux-arm-gnueabihf  1.2.14   0           -
npm        @rolldown/binding-linux-arm64-gnu      1.2.14   0           -
npm        @rolldown/binding-linux-arm64-musl     1.2.14   0           -
npm        @rolldown/binding-linux-ppc64-gnu      1.2.14   0           -
npm        @rolldown/binding-linux-s390x-gnu      1.2.14   0           -
npm        @rolldown/binding-linux-x64-gnu        1.2.14   0           -
npm        @rolldown/binding-linux-x64-musl       1.2.14   0           -
npm        @rolldown/binding-openharmony-arm64    1.2.14   0           -
npm        @rolldown/binding-win32-arm64-msvc     1.2.14   0           -
npm        @rolldown/binding-win32-x64-msvc       1.2.14   0           -
npm        @rolldown/pluginutils                  1.0.1    0           -
npm        @testing-library/dom                   10.4.2   0           -
npm        @testing-library/jest-dom              6.9.1    0           -
npm        @testing-library/react                 16.3.3   0           -
npm        @types/aria-query                      5.0.4    0           -
npm        @types/chai                            5.2.3    0           -
npm        @types/cytoscape                       3.21.9   0           -
npm        @types/deep-eql                        4.0.2    0           -
npm        @types/estree                          1.0.9    0           -
npm        @types/json-schema                     7.0.15   0           -
npm        @types/prop-types                      15.7.15  0           -
npm        @types/react                           18.3.31  0           -
npm        @types/react-dom                       18.3.7   0           -
npm        @typescript-eslint/eslint-plugin       8.71.2   0           -
npm        @typescript-eslint/parser              8.71.2   0           -
npm        @typescript-eslint/project-service     8.71.2   0           -
npm        @typescript-eslint/scope-manager       8.71.2   0           -
npm        @typescript-eslint/tsconfig-utils      8.71.2   0           -
npm        @typescript-eslint/type-utils          8.71.2   0           -
npm        @typescript-eslint/types               8.71.2   0           -
npm        @typescript-eslint/typescript-estree   8.71.2   0           -
npm        @typescript-eslint/utils               8.71.2   0           -
npm        @typescript-eslint/visitor-keys        8.71.2   0           -
npm        @vitejs/plugin-react                   6.1.2    0           -
npm        @vitest/mocker                         5.0.5    0           -
npm        @vitest/spy                            5.0.5    0           -
npm        acorn                                  8.19.0   0           -
npm        acorn-jsx                              5.3.2    0           -
npm        agent-base                             7.1.4    0           -
npm        ajv                                    6.15.0   0           -
npm        ansi-regex                             5.0.1    0           -
npm        ansi-styles                            4.3.0    0           -
npm        ansi-styles                            5.2.0    0           -
npm        argparse                               2.0.1    0           -
npm        aria-query                             5.3.0    0           -
npm        assertion-error                        2.0.1    0           -
npm        asynckit                               0.4.0    0           -
npm        balanced-match                         1.0.2    0           -
npm        balanced-match                         4.0.4    0           -
npm        brace-expansion                        1.1.21   0           -
npm        brace-expansion                        5.0.12   0           -
npm        call-bind-apply-helpers                1.0.2    0           -
npm        callsites                              3.1.0    0           -
npm        chai                                   6.3.0    0           -
npm        chalk                                  4.1.2    0           -
npm        color-convert                          2.0.1    0           -
npm        color-name                             1.1.4    0           -
npm        combined-stream                        1.0.8    0           -
npm        concat-map                             0.0.1    0           -
npm        cross-spawn                            7.0.6    0           -
npm        css.escape                             1.5.1    0           -
npm        cssstyle                               4.6.0    0           -
npm        csstype                                3.2.3    0           -
npm        cytoscape                              3.34.4   0           -
npm        data-urls                              5.0.0    0           -
npm        debug                                  4.4.3    0           -
npm        decimal.js                             10.6.0   0           -
npm        deep-is                                0.1.4    0           -
npm        delayed-stream                         1.0.0    0           -
npm        dequal                                 2.0.3    0           -
npm        detect-libc                            2.1.2    0           -
npm        dom-accessibility-api                  0.5.16   0           -
npm        dom-accessibility-api                  0.6.3    0           -
npm        dunder-proto                           1.0.1    0           -
npm        entities                               6.0.1    0           -
npm        es-define-property                     1.0.1    0           -
npm        es-errors                              1.3.0    0           -
npm        es-module-lexer                        2.3.2    0           -
npm        es-object-atoms                        1.1.2    0           -
npm        es-set-tostringtag                     2.1.0    0           -
npm        escape-string-regexp                   4.0.0    0           -
npm        eslint                                 9.39.5   0           -
npm        eslint-plugin-react-hooks              5.2.0    0           -
npm        eslint-scope                           8.4.0    0           -
npm        eslint-visitor-keys                    3.4.3    0           -
npm        eslint-visitor-keys                    4.2.1    0           -
npm        eslint-visitor-keys                    5.0.1    0           -
npm        espree                                 10.4.0   0           -
npm        esquery                                1.7.0    0           -
npm        esrecurse                              4.3.0    0           -
npm        estraverse                             5.3.0    0           -
npm        estree-walker                          3.0.3    0           -
npm        esutils                                2.0.3    0           -
npm        expect-type                            1.4.0    0           -
npm        fast-deep-equal                        3.1.3    0           -
npm        fast-json-stable-stringify             2.1.0    0           -
npm        fast-levenshtein                       2.0.6    0           -
npm        fdir                                   6.5.0    0           -
npm        file-entry-cache                       8.0.0    0           -
npm        find-up                                5.0.0    0           -
npm        flat-cache                             4.0.1    0           -
npm        flatted                                3.4.4    0           -
npm        form-data                              4.0.6    0           -
npm        fsevents                               2.3.3    0           -
npm        function-bind                          1.1.2    0           -
npm        get-intrinsic                          1.3.0    0           -
npm        get-proto                              1.0.1    0           -
npm        glob-parent                            6.0.2    0           -
npm        globals                                14.0.0   0           -
npm        gopd                                   1.2.0    0           -
npm        has-flag                               4.0.0    0           -
npm        has-symbols                            1.1.0    0           -
npm        has-tostringtag                        1.0.2    0           -
npm        hasown                                 2.0.4    0           -
npm        html-encoding-sniffer                  4.0.0    0           -
npm        http-proxy-agent                       7.0.2    0           -
npm        https-proxy-agent                      7.0.6    0           -
npm        iconv-lite                             0.6.3    0           -
npm        ignore                                 5.3.2    0           -
npm        ignore                                 7.0.12   0           -
npm        import-fresh                           3.3.1    0           -
npm        imurmurhash                            0.1.4    0           -
npm        indent-string                          4.0.0    0           -
npm        is-extglob                             2.1.1    0           -
npm        is-glob                                4.0.3    0           -
npm        is-potential-custom-element-name       1.0.1    0           -
npm        isexe                                  2.0.0    0           -
npm        js-tokens                              4.0.0    0           -
npm        js-yaml                                4.3.2    0           -
npm        jsdom                                  25.0.1   0           -
npm        json-buffer                            3.0.1    0           -
npm        json-schema-traverse                   0.4.1    0           -
npm        json-stable-stringify-without-jsonify  1.0.1    0           -
npm        keyv                                   4.5.4    0           -
npm        levn                                   0.4.1    0           -
npm        lightningcss                           1.33.0   0           -
npm        lightningcss-android-arm64             1.33.0   0           -
npm        lightningcss-darwin-arm64              1.33.0   0           -
npm        lightningcss-darwin-x64                1.33.0   0           -
npm        lightningcss-freebsd-x64               1.33.0   0           -
npm        lightningcss-linux-arm-gnueabihf       1.33.0   0           -
npm        lightningcss-linux-arm64-gnu           1.33.0   0           -
npm        lightningcss-linux-arm64-musl          1.33.0   0           -
npm        lightningcss-linux-x64-gnu             1.33.0   0           -
npm        lightningcss-linux-x64-musl            1.33.0   0           -
npm        lightningcss-win32-arm64-msvc          1.33.0   0           -
npm        lightningcss-win32-x64-msvc            1.33.0   0           -
npm        locate-path                            6.0.0    0           -
npm        lodash.merge                           4.6.2    0           -
npm        loose-envify                           1.4.0    0           -
npm        lru-cache                              10.4.3   0           -
npm        lz-string                              1.5.0    0           -
npm        magic-string                           1.4.3    0           -
npm        math-intrinsics                        1.1.0    0           -
npm        mime-db                                1.52.0   0           -
npm        mime-types                             2.1.35   0           -
npm        min-indent                             1.0.1    0           -
npm        minimatch                              10.2.6   0           -
npm        minimatch                              3.1.5    0           -
npm        ms                                     2.1.3    0           -
npm        nanoid                                 3.3.20   0           -
npm        natural-compare                        1.4.0    0           -
npm        nwsapi                                 2.2.28   0           -
npm        obug                                   3.0.0    0           -
npm        optionator                             0.9.4    0           -
npm        p-limit                                3.1.0    0           -
npm        p-locate                               5.0.0    0           -
npm        parent-module                          1.0.1    0           -
npm        parse5                                 7.3.0    0           -
npm        path-exists                            4.0.0    0           -
npm        path-key                               3.1.1    0           -
npm        picocolors                             1.1.1    0           -
npm        picomatch                              4.0.7    0           -
npm        postcss                                8.5.30   0           -
npm        prelude-ls                             1.2.1    0           -
npm        pretty-format                          27.5.1   0           -
npm        punycode                               2.3.1    0           -
npm        react                                  18.3.1   0           -
npm        react-dom                              18.3.1   0           -
npm        react-is                               17.0.2   0           -
npm        redent                                 3.0.0    0           -
npm        resolve-from                           4.0.0    0           -
npm        rolldown                               1.2.14   0           -
npm        rrweb-cssom                            0.7.1    0           -
npm        rrweb-cssom                            0.8.0    0           -
npm        safer-buffer                           2.1.2    0           -
npm        saxes                                  6.0.0    0           -
npm        scheduler                              0.23.2   0           -
npm        semver                                 7.8.5    0           -
npm        shebang-command                        2.0.0    0           -
npm        shebang-regex                          3.0.0    0           -
npm        source-map-js                          1.2.2    0           -
npm        std-env                                4.3.0    0           -
npm        strip-indent                           3.0.0    0           -
npm        strip-json-comments                    3.1.1    0           -
npm        supports-color                         7.2.0    0           -
npm        symbol-tree                            3.2.4    0           -
npm        tinybench                              6.2.2    0           -
npm        tinyexec                               1.3.1    0           -
npm        tinyglobby                             0.2.17   0           -
npm        tldts                                  6.1.86   0           -
npm        tldts-core                             6.1.86   0           -
npm        tough-cookie                           5.1.2    0           -
npm        tr46                                   5.1.1    0           -
npm        ts-api-utils                           2.5.0    0           -
npm        type-check                             0.4.0    0           -
npm        typescript                             5.9.3    0           -
npm        typescript-eslint                      8.71.2   0           -
npm        uri-js                                 4.4.1    0           -
npm        vite                                   8.3.4    0           -
npm        vitest                                 5.0.5    0           -
npm        w3c-xmlserializer                      5.0.0    0           -
npm        webidl-conversions                     7.0.0    0           -
npm        whatwg-encoding                        3.1.1    0           -
npm        whatwg-mimetype                        4.0.0    0           -
npm        whatwg-url                             14.2.0   0           -
npm        which                                  2.0.2    0           -
npm        why-is-node-running                    3.2.1    0           -
npm        word-wrap                              1.2.5    0           -
npm        ws                                     8.22.0   0           -
npm        xml-name-validator                     5.0.0    0           -
npm        xmlchars                               2.2.0    0           -
npm        yocto-queue                            0.1.0    0           -

checked 256 package versions, 0 with advisories
```

### npm audit output

```
found 0 vulnerabilities
```

### Findings

None. Every listed npm version has 0 OSV advisories, and `npm audit` reports 0 vulnerabilities, so no version change is needed.

### Re-run

Run `python3 -I scripts/check_vulns.py frontend/package-lock.json` from the repo root, then `npm audit` from `frontend/`. Both are read-only.

## Container base image tags (T1.12)

Plan §9.2 record. Lists every base image named in the plan's §8.1 services table, with the tag this project pins. No `latest` is used except where it is named here as a flagged exception.

### Run

- Date: 2026-10-16
- Method: read-only tag metadata lookups. Docker Hub tag list API (`hub.docker.com/v2/repositories/<repo>/tags`) for the Docker Hub images, and the public Chainguard image directory page (`images.chainguard.dev/directory/image/minio/versions`) for minio. The `cgr.dev` registry tag list returned HTTP 401 without credentials, so it was not used.
- No image was pulled, run, or scanned. `docker` was not invoked.

### Pinned tags

| Image:tag | Ecosystem / vendor | Used in | Date checked | Notes |
|---|---|---|---|---|
| `python:3.14.8-slim-trixie` | Python, Docker official | `backend/Dockerfile` base (T3.1). Candidate only | 2026-10-16 | Candidate, not yet used by a Dockerfile. Python 3.14 per AGENT.md §7. Debian trixie slim. |
| `node:24.22.0-trixie-slim` | Node.js, Docker official | `frontend/Dockerfile` build stage (Phase 7/8). Candidate only | 2026-10-16 | Candidate, not yet used by a Dockerfile. Node 24 is the Krypton LTS line on Docker Hub (`lts-krypton`). Node 26.12.0 also exists on Hub. The owner decides which line to use. |
| `nginx:1.30.6-alpine3.24` | nginx, Docker official | `frontend/Dockerfile` runtime stage (Phase 7/8). Candidate only | 2026-10-16 | Candidate, not yet used by a Dockerfile. nginx stable branch. |
| `neo4j:5.26.32-community` | Neo4j, Docker official | `neo4j` service (plan §8.1) | 2026-10-16 | Plan names `neo4j:5`. This is the newest 5.x patch on Hub at check time, community edition. |
| `mysql:8.4.11` | Oracle, Docker official | `mysql` service (plan §8.1) | 2026-10-16 | Plan names `mysql:8.4` (LTS). Exact patch pinned. |
| `postgres:17.11` | PostgreSQL, Docker official | `postgres` service, Langfuse database (plan §8.1) | 2026-10-16 | Plan names `postgres:${POSTGRES_VERSION}` with 17. The value of `POSTGRES_VERSION` should be `17.11` (driver or owner sets it in `.env`). |
| `clickhouse/clickhouse-server:25.12.11.4` | ClickHouse Inc. | `clickhouse` service, Langfuse (plan §8.1) | 2026-10-16 | Plan names the 25.12 upstream Langfuse tag. This is the newest 25.12 patch on Hub at check time. Default Debian-based variant, not `-alpine` or `-distroless`. |
| `redis:7.4.11` | Redis, Docker official | `redis` service, Langfuse (plan §8.1) | 2026-10-16 | Plan names `redis:7`. This is the newest 7.x patch on Hub at check time. An 8.x line also exists. The plan says 7, so no change was made. |
| `cgr.dev/chainguard/minio:0.20260922.192518` | Chainguard | `minio` service, Langfuse S3 storage (plan §8.1) | 2026-10-16 | **FLAGGED EXCEPTION.** The plan names `cgr.dev/chainguard/minio` with no tag. Chainguard's public directory lists only the rolling tags `latest` and `latest-dev`, plus date-stamped version tags. This row uses the newest listed date-stamped tag so the image is not `latest`. The `cgr.dev` tag list needs credentials, so this exact tag was not confirmed on the registry. The driver or owner must confirm the tag and the upstream Langfuse choice. |
| `docker.langfuse.com/langfuse/langfuse:4` | Langfuse | `langfuse-web` (plan §8.1) | 2026-10-16 | Transcribed as the plan gives it. This is a major-only tag, not an exact patch tag. Re-checking the exact patch is a later task. Docker Hub mirror shows `4.59.0` as the newest 4.x at check time. |
| `docker.langfuse.com/langfuse/langfuse-worker:4` | Langfuse | `langfuse-worker` (plan §8.1) | 2026-10-16 | Same as the row above. Transcribed as given. Docker Hub mirror shows `4.59.0` as the newest 4.x at check time. |

### Vulnerability status

- No image-level vulnerability scan was run. No scanner is installed in this environment (`trivy` and `docker scout` are absent), and `docker` is not run by agents (AGENT.md §4).
- OSV (`https://api.osv.dev/v1/query`) does not hold records keyed to these container tags, so this table makes no vulnerability claim.
- The tags above are listed so the owner, or a future CI step, can scan them. Every tag in this table must be scanned before the first `docker compose up` on a new host.

### Findings

None recorded. The table is a list of tags only. No scan result was produced.

### Re-run

Repeat the tag lookups above (Docker Hub tag API, Chainguard directory page) and compare against the table. Update this section with a new run section when a tag changes. Do not overwrite the earlier run.
