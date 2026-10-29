# Dependency licenses

A generated list of the third-party packages that go into the backend and frontend images. It is the
per-package companion to [THIRD_PARTY.md](../THIRD_PARTY.md), which holds the summary, the review
decisions and everything that is not a PyPI or npm package. Do not edit the tables by hand.

Scope: the **production** dependency tree only.

- Backend: the 74 packages in `backend/uv.lock` that `uv sync --frozen --no-dev` installs on CPython. The
  PyPy-only `brotlicffi` (pulled in by `fonttools[woff]`) is not installed, so it is not listed; PyPI
  declares it MIT.
- Frontend: `license-checker --production`, 120 packages. It also counts optional peers of the build
  tools (`vite`, `terser`, `lightningcss`, `typescript`); those run at build time and are not in the
  bundle the browser downloads.
- The project's own packages (`tartarus-backend`, `tartarus-frontend`) are left out; both are GPL-3.0-only.
- Not packages, so not listed: the 7-Zip console build the `cape` image installs in the analyzer (7-Zip 26.03,
  LGPL-2.1-or-later, no RAR code). It is in the `cape` image table of [THIRD_PARTY.md](../THIRD_PARTY.md), with
  its pinned hash and a link to its [license text](https://www.7-zip.org/license.txt).

The license column is what each package declares, so one license can appear under several spellings
(`MIT` and `MIT License`; `BSD License` and `BSD-3-Clause`). `guacamole-common-js` shows `BSD*` because
`license-checker` could not parse its metadata; its `LICENSE` file is the Apache License 2.0 and its
`package.json` says `Apache 2.0`.

## Regenerate

Save the script in the box below as `render.py` and run the commands from the repository root. The
last command writes the two tables to `/tmp/tables.md` and prints the per-license counts that
[THIRD_PARTY.md](../THIRD_PARTY.md) quotes; paste the tables over everything below the **Packages** heading.

```bash
(cd frontend && npx license-checker --production --excludePrivatePackages --json > /tmp/npm-licenses.json)
(cd backend && UV_PROJECT_ENVIRONMENT=/tmp/tartarus-license-venv uv sync --frozen --no-dev \
  && uvx pip-licenses --python=/tmp/tartarus-license-venv/bin/python --from=mixed --with-urls \
       --format=json --output-file=/tmp/py-licenses.json)
python3 -I render.py /tmp/npm-licenses.json /tmp/py-licenses.json /tmp/tables.md
```

<details>
<summary>render.py</summary>

```python
import collections
import json
import sys

npm_json, py_json = sys.argv[1:3]


def family(license_text: str) -> str:
    text = license_text.lower()
    if text.startswith("gnu general public license v2 or later"):
        return "GPL-2.0+ / LGPL-2.1+ / MPL-1.1 (tri-licensed, pyphen)"
    if "lgpl" in text or "lesser" in text:
        return "LGPL"
    if "mozilla" in text or "mpl" in text:
        return "MPL-2.0"
    found = {
        name
        for name, keys in {
            "Apache-2.0": ("apache",),
            "BSD": ("bsd",),
            "MIT": ("mit",),
            "ISC": ("isc",),
            "PSF-2.0": ("psf", "python software"),
            "0BSD": ("0bsd",),
        }.items()
        if any(key in text for key in keys)
    }
    if "0BSD" in found:
        found -= {"BSD"}
    if len(found) == 1:
        return found.pop()
    return "several permissive licenses combined" if found else "other: " + license_text


def summary(counter: collections.Counter) -> str:
    return "\n".join(f"| {name} | {count} |" for name, count in counter.most_common())


npm = json.load(open(npm_json))
npm_rows = sorted((name, value["licenses"], value.get("repository") or "") for name, value in npm.items())
py = json.load(open(py_json))
py_rows = sorted((row["Name"].lower(), row["Version"], row["License"], row["URL"]) for row in py)

out = []
out.append("\n### Backend (PyPI)\n")
out.append("| Package | Version | License (as the package declares it) | URL |\n|---|---|---|---|")
out += [f"| {n} | {v} | {l} | {u} |" for n, v, l, u in py_rows]
out.append("\n### Frontend (npm)\n")
out.append("| Package | License (as the package declares it) | Repository |\n|---|---|---|")
out += [f"| {n} | {l} | {r} |" for n, l, r in npm_rows]
open(sys.argv[3], "w").write("\n".join(out) + "\n")
print("PY families")
print(summary(collections.Counter(family(r[2]) for r in py_rows)))
print("NPM families")
print(summary(collections.Counter(family(r[1]) for r in npm_rows)))
```

</details>

## Packages

### Backend (PyPI)

| Package | Version | License (as the package declares it) | URL |
|---|---|---|---|
| aiohappyeyeballs | 2.7.1 | Python Software Foundation License | https://github.com/aio-libs/aiohappyeyeballs |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT | https://github.com/aio-libs/aiohttp |
| aiosignal | 1.4.0 | Apache Software License | https://github.com/aio-libs/aiosignal |
| alembic | 1.20.0 | MIT | https://alembic.sqlalchemy.org |
| annotated-doc | 0.0.5 | MIT | https://github.com/fastapi/annotated-doc |
| annotated-types | 0.8.0 | MIT | https://github.com/annotated-types/annotated-types |
| anyio | 4.15.1 | MIT | https://anyio.readthedocs.io/en/stable/versionhistory.html |
| asyncpg | 0.32.0 | Apache-2.0 | n/a |
| attrs | 26.1.0 | MIT | https://www.attrs.org/en/stable/changelog.html |
| brotli | 1.2.0 | MIT | https://github.com/google/brotli |
| certifi | 2026.10.19 | Mozilla Public License 2.0 (MPL 2.0) | https://github.com/certifi/python-certifi |
| cffi | 2.1.1 | MIT-0 | https://cffi.readthedocs.io/en/latest/whatsnew.html |
| charset-normalizer | 3.5.2 | MIT | https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md |
| click | 8.5.0 | BSD-3-Clause | https://github.com/pallets/click/ |
| cssselect2 | 0.10.1 | BSD License | https://doc.courtbouillon.org/cssselect2/ |
| diskcache | 5.6.3 | Apache Software License | http://www.grantjenks.com/docs/diskcache/ |
| diskcache-stubs | 5.6.3.6.20240818 | Apache Software License | https://github.com/phi-friday/diskcache-stubs |
| events | 0.5 | BSD License | http://github.com/pyeve/events |
| fastapi | 0.143.0 | MIT | https://github.com/fastapi/fastapi |
| fonttools | 4.67.0 | MIT | http://github.com/fonttools/fonttools |
| frozenlist | 1.8.0 | Apache-2.0 | https://github.com/aio-libs/frozenlist |
| google-re2 | 1.1.20251105 | BSD License | https://github.com/google/re2 |
| greenlet | 3.5.6 | MIT AND PSF-2.0 | https://greenlet.readthedocs.io |
| grpcio | 1.84.0 | Apache-2.0 | https://grpc.io |
| h11 | 0.16.0 | MIT License | https://github.com/python-hyper/h11 |
| httpcore | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ |
| httptools | 0.9.0 | MIT | https://github.com/MagicStack/httptools |
| httpx | 0.28.1 | BSD License | https://github.com/encode/httpx |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna |
| jinja2 | 3.1.6 | BSD License | https://github.com/pallets/jinja/ |
| jq | 1.12.0 | BSD-2-Clause | https://github.com/mwilliamson/jq.py |
| lark | 1.3.1 | MIT License | https://github.com/lark-parser/lark |
| mako | 1.4.3 | MIT | https://www.makotemplates.org/ |
| markupsafe | 3.0.4 | BSD-3-Clause | https://github.com/pallets/markupsafe/ |
| multidict | 7.1.0 | Apache-2.0 | https://github.com/aio-libs/multidict |
| opensearch-protobufs | 1.2.0 | Apache Software License | https://opensearch.org/ |
| opensearch-py | 3.2.0 | Apache Software License | https://github.com/opensearch-project/opensearch-py |
| opentelemetry-api | 1.45.1 | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-api |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| pillow | 13.0.0 | MIT-CMU | https://python-pillow.org |
| propcache | 0.5.4 | Apache-2.0 | https://github.com/aio-libs/propcache |
| protobuf | 7.36.2 | 3-Clause BSD License | https://developers.google.com/protocol-buffers/ |
| pycparser | 3.11 | BSD-3-Clause | https://github.com/eliben/pycparser |
| pycryptodomex | 3.24.1 | BSD License; Public Domain | https://www.pycryptodome.org |
| pydantic | 2.14.1 | MIT | https://github.com/pydantic/pydantic |
| pydantic-settings | 2.15.0 | MIT | https://github.com/pydantic/pydantic-settings |
| pydantic_core | 2.50.1 | MIT | https://github.com/pydantic |
| pydyf | 0.13.0 | BSD License | https://www.courtbouillon.org/pydyf |
| pyparsing | 3.3.3 | MIT | https://github.com/pyparsing/pyparsing/ |
| pyphen | 0.18.1 | GNU General Public License v2 or later (GPLv2+); GNU Lesser General Public License v2 or later (LGPLv2+); Mozilla Public License 1.1 (MPL 1.1) | https://www.courtbouillon.org/pyphen |
| pysigma | 2.0.1 | LGPL-2.1-only | https://github.com/SigmaHQ/pySigma |
| python-dateutil | 2.9.0.post0 | Apache Software License; BSD License | https://github.com/dateutil/dateutil |
| python-dotenv | 1.2.4 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| python-multipart | 0.0.32 | Apache-2.0 | https://github.com/Kludex/python-multipart |
| pyyaml | 6.0.3 | MIT License | https://pyyaml.org/ |
| pyzipper | 0.4.0 | MIT | https://github.com/danifus/pyzipper |
| requests | 2.34.2 | Apache Software License | https://github.com/psf/requests |
| six | 1.17.0 | MIT License | https://github.com/benjaminp/six |
| sqlalchemy | 2.1.4 | MIT | https://www.sqlalchemy.org |
| starlette | 1.7.0 | BSD-3-Clause | https://github.com/Kludex/starlette |
| tinycss2 | 1.5.1 | BSD License | https://www.courtbouillon.org/tinycss2 |
| tinyhtml5 | 2.1.0 | MIT License | https://github.com/CourtBouillon/tinyhtml5 |
| types-pyyaml | 6.0.12.20260906 | Apache-2.0 | https://github.com/python/typeshed |
| typing-inspection | 0.4.4 | MIT | https://github.com/pydantic/typing-inspection |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| urllib3 | 2.8.0 | MIT | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst |
| uvicorn | 0.54.0 | BSD-3-Clause | https://uvicorn.dev/ |
| uvloop | 0.23.0 | Apache Software License; MIT License | n/a |
| watchfiles | 1.3.0 | MIT License | https://github.com/samuelcolvin/watchfiles |
| weasyprint | 70.0 | BSD License | https://weasyprint.org/ |
| webencodings | 0.6.1 | BSD License | https://github.com/CourtBouillon/webencodings |
| websockets | 17.2 | BSD-3-Clause | https://github.com/python-websockets/websockets |
| yarl | 1.25.1 | Apache-2.0 | https://github.com/aio-libs/yarl |
| zopfli | 0.4.3 | Apache Software License | https://github.com/fonttools/py-zopfli |

### Frontend (npm)

| Package | License (as the package declares it) | Repository |
|---|---|---|
| @babel/helper-string-parser@7.29.7 | MIT | https://github.com/babel/babel |
| @babel/helper-string-parser@8.0.6 | MIT | https://github.com/babel/babel |
| @babel/helper-validator-identifier@7.29.7 | MIT | https://github.com/babel/babel |
| @babel/helper-validator-identifier@8.0.6 | MIT | https://github.com/babel/babel |
| @babel/parser@7.29.9 | MIT | https://github.com/babel/babel |
| @babel/parser@8.0.7 | MIT | https://github.com/babel/babel |
| @babel/types@7.29.8 | MIT | https://github.com/babel/babel |
| @babel/types@8.0.6 | MIT | https://github.com/babel/babel |
| @bufbuild/protobuf@2.16.0 | (Apache-2.0 AND BSD-3-Clause) | https://github.com/bufbuild/protobuf-es |
| @intlify/core-base@11.4.16 | MIT | https://github.com/intlify/vue-i18n |
| @intlify/devtools-types@11.4.16 | MIT | https://github.com/intlify/vue-i18n |
| @intlify/message-compiler@11.4.16 | MIT | https://github.com/intlify/vue-i18n |
| @intlify/shared@11.4.16 | MIT | https://github.com/intlify/vue-i18n |
| @jridgewell/gen-mapping@0.3.13 | MIT | https://github.com/jridgewell/sourcemaps |
| @jridgewell/remapping@2.3.5 | MIT | https://github.com/jridgewell/sourcemaps |
| @jridgewell/resolve-uri@3.1.2 | MIT | https://github.com/jridgewell/resolve-uri |
| @jridgewell/source-map@0.3.11 | MIT | https://github.com/jridgewell/sourcemaps |
| @jridgewell/sourcemap-codec@1.6.0 | MIT | https://github.com/jridgewell/sourcemaps |
| @jridgewell/trace-mapping@0.3.31 | MIT | https://github.com/jridgewell/sourcemaps |
| @napi-rs/lzma-linux-x64-gnu@1.5.1 | MIT | https://github.com/Brooooooklyn/lzma |
| @oxc-project/types@0.153.0 | MIT | https://github.com/oxc-project/oxc |
| @parcel/watcher-linux-x64-glibc@2.6.0 | MIT | https://github.com/parcel-bundler/watcher |
| @parcel/watcher@2.6.0 | MIT | https://github.com/parcel-bundler/watcher |
| @quasar/extras@2.1.0 | MIT | https://github.com/quasarframework/quasar |
| @rolldown/binding-linux-x64-gnu@1.2.13 | MIT | https://github.com/rolldown/rolldown |
| @rolldown/pluginutils@1.0.1 | MIT | https://github.com/rolldown/plugins |
| @rollup/rollup-linux-x64-gnu@4.64.5 | MIT | https://github.com/rollup/rollup |
| @types/estree@1.0.9 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/node@24.19.2 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @vue-macros/common@3.1.4 | MIT | https://github.com/vue-macros/vue-macros |
| @vue/compiler-core@3.5.43 | MIT | https://github.com/vuejs/core |
| @vue/compiler-dom@3.5.43 | MIT | https://github.com/vuejs/core |
| @vue/compiler-sfc@3.5.43 | MIT | https://github.com/vuejs/core |
| @vue/compiler-ssr@3.5.43 | MIT | https://github.com/vuejs/core |
| @vue/devtools-api@6.6.4 | MIT | https://github.com/vuejs/vue-devtools |
| @vue/devtools-api@8.2.1 | MIT | https://github.com/vuejs/devtools |
| @vue/devtools-kit@8.2.1 | MIT | https://github.com/vuejs/devtools |
| @vue/devtools-shared@8.2.1 | MIT | https://github.com/vuejs/devtools |
| @vue/reactivity@3.5.43 | MIT | https://github.com/vuejs/core |
| @vue/runtime-core@3.5.43 | MIT | https://github.com/vuejs/core |
| @vue/runtime-dom@3.5.43 | MIT | https://github.com/vuejs/core |
| @vue/server-renderer@3.5.43 | MIT | https://github.com/vuejs/core |
| @vue/shared@3.5.43 | MIT | https://github.com/vuejs/core |
| acorn@8.19.0 | MIT | https://github.com/acornjs/acorn |
| ast-kit@2.2.0 | MIT | https://github.com/sxzz/ast-kit |
| ast-kit@3.0.0 | MIT | https://github.com/sxzz/ast-kit |
| ast-walker-scope@0.10.0 | MIT | https://github.com/sxzz/ast-walker-scope |
| birpc@2.9.0 | MIT | https://github.com/antfu-collective/birpc |
| buffer-from@1.1.2 | MIT | https://github.com/LinusU/buffer-from |
| chokidar@5.0.0 | MIT | https://github.com/paulmillr/chokidar |
| colorjs.io@0.7.1 | MIT | https://github.com/color-js/color.js |
| commander@2.20.3 | MIT | https://github.com/tj/commander.js |
| confbox@0.1.8 | MIT | https://github.com/unjs/confbox |
| confbox@0.3.1 | MIT | https://github.com/unjs/confbox |
| csstype@3.2.3 | MIT | https://github.com/frenic/csstype |
| cytoscape-dagre@4.0.1 | MIT | https://github.com/cytoscape/cytoscape.js-dagre |
| cytoscape@3.34.3 | MIT | https://github.com/cytoscape/cytoscape.js |
| detect-libc@2.1.2 | Apache-2.0 | https://github.com/lovell/detect-libc |
| entities@7.0.1 | BSD-2-Clause | https://github.com/fb55/entities |
| estree-walker@2.0.2 | MIT | https://github.com/Rich-Harris/estree-walker |
| estree-walker@3.0.3 | MIT | https://github.com/Rich-Harris/estree-walker |
| exsolve@1.1.3 | MIT | https://github.com/unjs/exsolve |
| fdir@6.5.0 | MIT | https://github.com/thecodrr/fdir |
| guacamole-common-js@1.5.0 | BSD* | https://github.com/padarom/guacamole-common-js |
| has-flag@4.0.0 | MIT | https://github.com/sindresorhus/has-flag |
| hookable@5.5.3 | MIT | https://github.com/unjs/hookable |
| immutable@5.1.9 | MIT | https://github.com/immutable-js/immutable-js |
| is-extglob@2.1.1 | MIT | https://github.com/jonschlinkert/is-extglob |
| is-glob@4.0.3 | MIT | https://github.com/micromatch/is-glob |
| jiti@2.7.0 | MIT | https://github.com/unjs/jiti |
| lightningcss-linux-x64-gnu@1.33.0 | MPL-2.0 | https://github.com/parcel-bundler/lightningcss |
| lightningcss@1.33.0 | MPL-2.0 | https://github.com/parcel-bundler/lightningcss |
| local-pkg@1.2.1 | MIT | https://github.com/antfu-collective/local-pkg |
| magic-string-ast@1.0.3 | MIT | https://github.com/sxzz/magic-string-ast |
| magic-string@0.30.21 | MIT | https://github.com/Rich-Harris/magic-string |
| magic-string@1.4.3 | MIT | https://github.com/Rich-Harris/magic-string |
| mlly@1.8.2 | MIT | https://github.com/unjs/mlly |
| muggle-string@0.4.1 | MIT | https://github.com/johnsoncodehk/muggle-string |
| nanoid@3.3.20 | MIT | https://github.com/ai/nanoid |
| node-addon-api@7.1.1 | MIT | https://github.com/nodejs/node-addon-api |
| nostics@1.3.0 | MIT | https://github.com/vercel-labs/nostics |
| pathe@2.0.3 | MIT | https://github.com/unjs/pathe |
| perfect-debounce@2.1.0 | MIT | https://github.com/unjs/perfect-debounce |
| picocolors@1.1.1 | ISC | https://github.com/alexeyraspopov/picocolors |
| picomatch@4.0.7 | MIT | https://github.com/micromatch/picomatch |
| pinia@4.0.3 | MIT | https://github.com/vuejs/pinia |
| pkg-types@1.3.1 | MIT | https://github.com/unjs/pkg-types |
| pkg-types@2.3.3 | MIT | https://github.com/unjs/pkg-types |
| postcss@8.5.29 | MIT | https://github.com/postcss/postcss |
| quansync@0.2.11 | MIT | https://github.com/quansync-dev/quansync |
| quasar@2.35.1 | MIT | https://github.com/quasarframework/quasar |
| readdirp@5.1.1 | MIT | https://github.com/paulmillr/readdirp |
| rolldown@1.2.13 | MIT | https://github.com/rolldown/rolldown |
| rollup@4.64.5 | MIT | https://github.com/rollup/rollup |
| rxjs@7.8.2 | Apache-2.0 | https://github.com/reactivex/rxjs |
| sass-embedded-linux-x64@1.105.1 | MIT | https://github.com/sass/embedded-host-node |
| sass-embedded@1.105.1 | MIT | https://github.com/sass/embedded-host-node |
| sass@1.105.1 | MIT | https://github.com/sass/dart-sass |
| scule@1.3.0 | MIT | https://github.com/unjs/scule |
| source-map-js@1.2.2 | BSD-3-Clause | https://github.com/7rulnik/source-map-js |
| source-map-support@0.5.21 | MIT | https://github.com/evanw/node-source-map-support |
| source-map@0.6.1 | BSD-3-Clause | https://github.com/mozilla/source-map |
| supports-color@8.1.1 | MIT | https://github.com/chalk/supports-color |
| sync-child-process@1.0.2 | MIT | https://github.com/sass/sync-child-process |
| sync-message-port@1.2.0 | MIT | https://github.com/sass/sync-message-port |
| terser@5.51.2 | BSD-2-Clause | https://github.com/terser/terser |
| tinyglobby@0.2.17 | MIT | https://github.com/SuperchupuDev/tinyglobby |
| tslib@2.8.1 | 0BSD | https://github.com/Microsoft/tslib |
| typescript@6.0.3 | Apache-2.0 | https://github.com/microsoft/TypeScript |
| ufo@1.6.4 | MIT | https://github.com/unjs/ufo |
| undici-types@7.24.6 | MIT | https://github.com/nodejs/undici |
| unplugin-utils@0.3.2 | MIT | https://github.com/sxzz/unplugin-utils |
| unplugin@3.4.0 | MIT | https://github.com/unjs/unplugin |
| varint@6.0.0 | MIT | https://github.com/chrisdickinson/varint |
| vite@8.3.4 | MIT | https://github.com/vitejs/vite |
| vue-i18n@11.4.16 | MIT | https://github.com/intlify/vue-i18n |
| vue-router@5.4.0 | MIT | https://github.com/vuejs/router |
| vue@3.5.43 | MIT | https://github.com/vuejs/core |
| webpack-virtual-modules@0.6.2 | MIT | https://github.com/sysgears/webpack-virtual-modules |
| yaml@2.9.1 | ISC | https://github.com/eemeli/yaml |
