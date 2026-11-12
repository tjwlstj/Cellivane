"""Build the Windows CPU worker against hash-pinned public b11429 headers.

No upstream source is built, no model is downloaded or run, and no input is
vendored into this repository.  A build receipt is evidence of compilation,
not evidence that a model generated a valid answer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from datetime import datetime, timezone

ENGINE_COMMIT = "d81235049384534c167caea52b85a694f6103d14"
ENGINE_TAG = "b11429"
ENGINE_ARCHIVE_SHA256 = "1283323272b04cd07905816a597a0da810918102de958f4ff6f7bbaa70ed2efe"
RAW = f"https://raw.githubusercontent.com/ggml-org/llama.cpp/{ENGINE_COMMIT}/"
INPUT_HASHES = {
    "include/llama.h": "c9a5f025ad7dbf07eda6660c8ff2c32cd80c07ba440d80728707a9c9d13c1bc3",
    "ggml/include/ggml.h": "12ee71f99db7db9b353bc02b1fbb57c344ee17c01ac5fb7952b41a637a747ea9",
    "ggml/include/ggml-cpu.h": "316279e004cdeb8e6ef78599acb602bf79a8abdf897fed9fd1914808c1518c6e",
    "ggml/include/ggml-backend.h": "5791edae1fb7622027621d15bc7a160198bd3b75ed8f96d06cb7b85e2b873756",
    "ggml/include/ggml-opt.h": "3586de1bc8a934b5c72339e2b6937b0641e8f149b512231e666f67de0736eea2",
    "ggml/include/gguf.h": "e56714aab702e5ce62ee587a409643c08f7e93e8fbb77f48ef7cc85075f96fa4",
    "ggml/include/ggml-alloc.h": "d114067f9099c4a0e2bbc0625c676d4894d9cf0ea27168ee072c7de0e71bb51d",
    "vendor/nlohmann/json.hpp": "aaf127c04cb31c406e5b04a63f1ae89369fccde6d8fa7cdda1ed4f32dfc5de63",
    "LICENSE": "94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d",
    "vendor/nlohmann/LICENSE.MIT": "46a65cffd1ea955132d95a8dd921640714a8d6b537d2e4e482d31145ae95b603",
}
INPUT_URLS = {path: RAW + path for path in INPUT_HASHES}
INPUT_URLS["vendor/nlohmann/LICENSE.MIT"] = (
    "https://raw.githubusercontent.com/nlohmann/json/55f93686c01528224f448c19128836e7df245f72/LICENSE.MIT"
)
DLL_HASHES = {
    "ggml-base.dll": "19b7666b4cd7dc01e219e247783ffd1979694d6f1635bbf3209ae5fa0fc169c0",
    "ggml.dll": "2dc74873c47a09294431af997f7d5c31bdbc0eafc49c2c30ea03b7331c1a5c3c",
    "llama.dll": "48d2b52f4d6b2d7db2ca4698edbb95ecb4511b792396c566e1340668b6415a71",
    "libomp.dll": "a12116ba72d1d6820407cf30be23da04ce79d6bb8a71a5ee71759c5a1faa6f1c",
    "ggml-cpu-alderlake.dll": "176045703530b923eb565052d9c622e1453c7013ac11823926f89260768cdddd",
    "ggml-cpu-cannonlake.dll": "c9723eab21d1d80e38f3791088739c56a8a36f7db5ad2340811eac2d3fd45af7",
    "ggml-cpu-cascadelake.dll": "1db7a13737763d444c278ac218ad9dc5dc850e1fcd98bc07ece307ae6f64dda6",
    "ggml-cpu-cooperlake.dll": "482a40664f87b8e94bdab53c13b14fa6b722ffd743a7a7c4fa7d5cec6ed44852",
    "ggml-cpu-haswell.dll": "8022a1d17a56f537b956683a484dc1a0f95ab4b01e95b4c57d53bb1e6c3e529f",
    "ggml-cpu-icelake.dll": "c096a02ec4a9fecca14a14bd9ed5d6c9fa7569cc2a678b08dd1978646abe1e2a",
    "ggml-cpu-ivybridge.dll": "1792967edf602b0a459cbb519e71a3037fba5854ba273b8328467c9d9dc201f1",
    "ggml-cpu-piledriver.dll": "b47a82e5d9087f03a54a840e848e4f2e0b44312309065e60b8d0cd421202233c",
    "ggml-cpu-sandybridge.dll": "007dc9fca693bf1e3941c1d46bb273de587c2d0947625884ccd68154d190e03c",
    "ggml-cpu-sapphirerapids.dll": "72b1203f01d4aa12f22d45415d91dc046f15e3eb3da49f7110b59c888bee9978",
    "ggml-cpu-skylakex.dll": "ccf578111e9688c2c51f0279ab4e56351fa084f7d6e43e7c091d961fdbb03081",
    "ggml-cpu-sse42.dll": "740d3e84289733501b70274904c9d1135bdc579babf7c82825f5ae0133e5afbd",
    "ggml-cpu-x64.dll": "b1089f3ad0cc1363519c3583b033648cf471297bdd5482e72c71dcf5c5cb0765",
    "ggml-cpu-zen4.dll": "7f257519148e3b81fc718acad0f7afcd381d2b429fe0032a1f97e365d7ff2db5",
    "LICENSE-LLVM-OpenMP": "fdad1758a9e1f9d5a81e18879b3406772115edc92c24bfa36b70c654f325e8e4",
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked(path: Path, expected: str) -> dict:
    if path.is_symlink() or not path.is_file() or digest(path) != expected:
        raise ValueError(f"pinned input mismatch: {path.name}")
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": expected}


def input_files(root: Path, *, download: bool = False) -> list[dict]:
    records = []
    for name, expected in INPUT_HASHES.items():
        path = root / name
        if not path.exists() and download:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".cellivane-input-", dir=path.parent)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    with urllib.request.urlopen(INPUT_URLS[name], timeout=30) as response:
                        body = response.read(2 * 1024 * 1024 + 1)
                    if len(body) > 2 * 1024 * 1024 or hashlib.sha256(body).hexdigest() != expected:
                        raise ValueError("download hash/size mismatch")
                    output.write(body)
                    output.flush()
                    os.fsync(output.fileno())
                if path.exists():
                    checked(path, expected)
                else:
                    os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        record = checked(path, expected)
        record.update(relative_path=name, url=INPUT_URLS[name])
        records.append(record)
    return records


def sealed_engine(source: Path, target: Path) -> list[dict]:
    # Never scan or copy arbitrary DLLs. Only CPU members of the verified archive.
    records = []
    target.mkdir(parents=True, exist_ok=False)
    for name, expected in DLL_HASHES.items():
        checked(source / name, expected)
        shutil.copyfile(source / name, target / name)
        record = checked(target / name, expected)
        record["relative_path"] = name
        records.append(record)
    return records


def batch_path(path: Path) -> str:
    value = str(path.resolve())
    # The compiler environment is loaded by a small .cmd, not a shell-built path.
    # Reject expansion/metacharacters rather than interpolating them into cmd.exe.
    if any(character in value for character in '%&|<>^!"\r\n'):
        raise ValueError("path cannot be represented safely in build command")
    return value


def save_json(path: Path, record: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(record, output, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def build(output_root: Path, engine_dir: Path, vs_root: Path, *, download_inputs: bool = False) -> dict:
    if os.name != "nt":
        raise ValueError("this worker build supports Windows x64 only")
    output_root = output_root.resolve()
    if str(output_root).startswith("\\\\") or not output_root.is_absolute():
        raise ValueError("build output must be an absolute local path")
    output_root.mkdir(parents=True, exist_ok=True)
    inputs_root = output_root / "build-inputs"
    inputs = input_files(inputs_root, download=download_inputs)
    repo = Path(__file__).resolve().parents[2]
    source = repo / "native/cellivane_runtime/worker.cpp"
    source_sha = digest(source)
    helper_sha = digest(Path(__file__))
    run = output_root / "builds" / str(uuid.uuid4())
    run.mkdir(parents=True, exist_ok=False)
    libraries = sealed_engine(engine_dir.resolve(), run / "engine-cpu")
    vcvars = vs_root / "VC/Auxiliary/Build/vcvars64.bat"
    if not vcvars.is_file():
        raise ValueError("Visual Studio x64 build environment was not found")
    executable = run / "cellivane-runtime-worker.exe"
    compiler_args = ["cl.exe", "/nologo", "/std:c++17", "/EHsc", "/O2", "/W4", "/MT", "/utf-8",
                     "/DUNICODE", "/D_UNICODE", "/D_WIN32_WINNT=0x0A00",
                     "/I" + batch_path(inputs_root / "include"), "/I" + batch_path(inputs_root / "ggml/include"),
                     "/I" + batch_path(inputs_root / "vendor/nlohmann"), batch_path(source),
                     "/Fe:" + batch_path(executable), "/Fo:" + batch_path(run / "worker.obj"),
                     "/link", "Psapi.lib", "Bcrypt.lib", "/DYNAMICBASE", "/NXCOMPAT"]
    command = run / "compile.cmd"
    command.write_text("@echo off\nsetlocal DisableDelayedExpansion\ncall \"" + batch_path(vcvars) +
                       "\" >nul\nif errorlevel 1 exit /b %errorlevel%\n" +
                       subprocess.list2cmdline(compiler_args) + "\nexit /b %errorlevel%\n", encoding="utf-8")
    process = subprocess.run(["cmd.exe", "/d", "/s", "/c", str(command)], cwd=run,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180, check=False)
    log = run / "build.log"
    log.write_bytes(process.stdout)
    receipt = {
        "schema_version": 1, "artifact_family": "cellivane-native-worker-build-v1",
        "outcome": "COMPILED" if process.returncode == 0 and executable.is_file() else "FAILED",
        "runtime_tested": False, "model_run": False,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "engine_commit": ENGINE_COMMIT, "engine_tag": ENGINE_TAG,
        "engine_archive_sha256": ENGINE_ARCHIVE_SHA256,
        "upstream_repository": "https://github.com/ggml-org/llama.cpp",
        "source": {"path": str(source), "sha256": source_sha},
        "builder": {"path": str(Path(__file__).resolve()), "sha256": helper_sha},
        "inputs": inputs, "engine_directory": str(run / "engine-cpu"), "engine_files": libraries,
        "compiler_arguments": compiler_args, "compiler_environment": str(vcvars),
        "exit_code": process.returncode, "build_log": {"path": str(log), "sha256": digest(log)},
        "executable": None,
        "scope": "Windows x64 CPU compilation only; no model qualification, paging, GPU, shared KV, or MTP",
    }
    if digest(source) != source_sha or digest(Path(__file__)) != helper_sha:
        receipt["outcome"] = "FAILED"
        receipt["source_changed_during_build"] = True
    # Recheck input/DLL bytes after the compiler completed.
    input_files(inputs_root)
    for name, expected in DLL_HASHES.items():
        checked(run / "engine-cpu" / name, expected)
    if executable.is_file():
        receipt["executable"] = {"path": str(executable), "sha256": digest(executable), "bytes": executable.stat().st_size}
    path = run / "build-receipt.json"
    save_json(path, receipt)
    return {"outcome": receipt["outcome"], "receipt": str(path), "receipt_sha256": digest(path),
            "executable": receipt["executable"], "engine_directory": receipt["engine_directory"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--engine-dir", type=Path, required=True)
    parser.add_argument("--vs-root", type=Path, default=Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/2022/BuildTools")
    parser.add_argument("--download-inputs", action="store_true", help="download only missing, hash-pinned public inputs")
    args = parser.parse_args(argv)
    try:
        result = build(args.output_root, args.engine_dir, args.vs_root, download_inputs=args.download_inputs)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"outcome": "FAILED", "error": type(error).__name__}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["outcome"] == "COMPILED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
