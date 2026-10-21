# Local delivery artifacts

Generate the versioned source ZIP and SHA-256 manifest from a clean committed checkout (or use `--committed-source` to package exact HEAD while retaining unrelated local edits):

```sh
python scripts/package_release.py --version 2.0.0-dev.20261021.1
```

ZIPs and manifests remain local delivery artifacts; GitHub stores their source. `BUILD_INFO.json` inside the ZIP records the exact source commit. The ZIP includes the prebuilt frontend and excludes runtime data, credentials, dependencies, model/browser caches and the `.git` directory.

`outputs/runtime/` contains ignored, isolated acceptance data and browser screenshots generated on this device. These are not personal installation data and are never packaged.
