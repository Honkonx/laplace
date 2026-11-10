#!/usr/bin/env python3
"""Escáner de la skill de seguridad: corre reglas HaE sobre archivos con ripgrep y emite un reporte JSON.

La lógica refleja la extensión HaEFile de Burp Suite: las reglas se agrupan por
(regex, sensitive), cada patrón corre una vez a través de `rg --json` (PCRE2 primero,
motor estándar como respaldo), y cada submatch se reduce al grupo de captura 1 cuando
el patrón define uno.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RULES = os.path.join(SKILL_DIR, "rules", "Rules.json")
DEFAULT_IGNORED_EXTENSIONS = [
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".webp",
    ".bmp",
]



def load_rules(path):
    """Devuelve una lista de reglas: group, name, regex, sensitive.

    Los archivos de reglas en JSON no necesitan nada fuera de la librería estándar.
    Un archivo `.yml` / `.yaml` igual se carga si PyYAML está instalado, así un
    archivo de reglas HaE existente puede apuntarse directamente.
    """
    with open(path, encoding="utf-8") as handle:
        if os.path.splitext(path)[1].lower() in (".yml", ".yaml"):
            try:
                import yaml
            except ImportError:
                sys.exit(
                    "%s es YAML; conviértelo a JSON o instala PyYAML (pip3 install pyyaml)"
                    % path
                )
            data = yaml.safe_load(handle) or {}
        else:
            try:
                data = json.load(handle) or {}
            except ValueError as exc:
                sys.exit("%s no es un JSON válido: %s" % (path, exc))
    rules = []
    for group in data.get("rules") or []:
        group_name = str(group.get("group") or "Sin Agrupar")
        for item in group.get("rule") or []:
            regex = item.get("regex")
            if not regex:
                continue
            rules.append(
                {
                    "group": group_name,
                    "name": str(item.get("name") or "Sin Nombre"),
                    "regex": str(regex),
                    "sensitive": bool(item.get("sensitive", False)),
                    "loaded": bool(item.get("loaded", True)),
                }
            )
    return rules


def select_rules(rules, groups, names):
    def hit(value, needles):
        return not needles or any(n.lower() in value.lower() for n in needles)

    return [
        r
        for r in rules
        if r["loaded"] and hit(r["group"], groups) and hit(r["name"], names)
    ]


def group_by_pattern(rules):
    """Agrupa reglas que comparten el mismo (regex, sensitive) para que ripgrep corra una sola vez."""
    buckets = {}
    for rule in rules:
        buckets.setdefault((rule["regex"], rule["sensitive"]), []).append(rule)
    return buckets



def build_rg_args(pattern, sensitive, opts, use_pcre2):
    args = ["--json", "--text", "--hidden", "--no-ignore", "--encoding", "auto"]
    if opts.max_count > 0:
        args += ["--max-count", str(opts.max_count)]
    if opts.max_filesize:
        args += ["--max-filesize", opts.max_filesize]
    if use_pcre2:
        args.append("--pcre2")
    if not sensitive:
        args.append("--ignore-case")
    for ext in opts.ignore_ext:
        args += ["--glob", f"!*{ext}"]
    args += ["--", pattern] + list(opts.targets)
    return args


def text_of(field):
    """rg emite {"text": "..."} o {"bytes": "<base64>"}."""
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        if isinstance(field.get("text"), str):
            return field["text"]
        if isinstance(field.get("bytes"), str):
            try:
                return base64.b64decode(field["bytes"]).decode("utf-8", "replace")
            except Exception:
                return ""
    return ""


def byte_to_char(text, byte_offset):
    """Convierte un offset en bytes de ripgrep a un índice de caracteres de `text`."""
    if byte_offset <= 0:
        return 0
    raw = text.encode("utf-8")
    if byte_offset >= len(raw):
        return len(text)
    aligned = byte_offset
    while aligned > 0 and raw[aligned] & 0xC0 == 0x80:
        aligned -= 1
    return len(raw[:aligned].decode("utf-8", "replace"))


def compile_capture(pattern, sensitive):
    try:
        return re.compile(pattern, 0 if sensitive else re.IGNORECASE)
    except re.error:
        return None


def capture_group(full, capture):
    """Reduce un match completo de ripgrep al grupo de captura 1, con su offset en bytes."""
    if capture is not None and capture.groups >= 1:
        found = capture.search(full)
        if found is not None and found.group(1):
            index = full.find(found.group(1))
            if index >= 0:
                return found.group(1), len(full[:index].encode("utf-8"))
    return full, 0


def parse_match_line(line, capture, context_window, sink):
    try:
        payload = json.loads(line)
    except ValueError:
        return
    if not isinstance(payload, dict) or payload.get("type") != "match":
        return
    data = payload.get("data") or {}
    line_number = data.get("line_number")
    submatches = data.get("submatches")
    if not isinstance(line_number, int) or not isinstance(submatches, list):
        return

    file_path = text_of(data.get("path"))
    line_text = text_of(data.get("lines")).rstrip("\r\n")
    for sub in submatches:
        if not isinstance(sub, dict) or not isinstance(sub.get("start"), int):
            continue
        full = text_of(sub.get("match"))
        if not full:
            continue
        value, offset = capture_group(full, capture)
        start = byte_to_char(line_text, sub["start"] + offset)
        end = min(len(line_text), start + len(value))
        before = line_text[max(0, start - context_window) : start] if context_window else ""
        after = line_text[end : end + context_window] if context_window else ""
        sink.append(
            {
                "file": file_path,
                "line": line_number,
                "column": start + 1,
                "match": value,
                "context": {"before": before, "after": after},
            }
        )


def run_ripgrep(pattern, sensitive, opts, use_pcre2):
    """Devuelve (matches, error). error es None si fue exitoso."""
    args = [opts.rg] + build_rg_args(pattern, sensitive, opts, use_pcre2)
    matches = []
    capture = compile_capture(pattern, sensitive)
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return [], f"no se pudo ejecutar ripgrep: {exc}"

    try:
        for line in proc.stdout:
            if line.strip():
                parse_match_line(line, capture, opts.context, matches)
        stderr = proc.stderr.read()
        proc.wait(timeout=opts.timeout if opts.timeout > 0 else None)
    except subprocess.TimeoutExpired:
        proc.kill()
        return matches, f"ripgrep excedió el tiempo límite de {opts.timeout}s"
    finally:
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except Exception:
                pass

    # código de salida 0 = matches, 1 = sin matches, >=2 = error
    if proc.returncode is not None and proc.returncode >= 2:
        return matches, (stderr or f"ripgrep terminó con código {proc.returncode}").strip()
    return matches, None


def scan_pattern(pattern, sensitive, opts):
    matches, error = run_ripgrep(pattern, sensitive, opts, use_pcre2=True)
    if error is None:
        return matches, None
    fallback, fallback_error = run_ripgrep(pattern, sensitive, opts, use_pcre2=False)
    if fallback_error is None:
        return fallback, None
    return [], fallback_error


def build_report(rules, buckets, results, errors, opts, duration_ms, rg_version):
    """Convierte los matches crudos en findings deduplicados más un resumen."""
    order = {(r["group"], r["name"]): i for i, r in enumerate(rules)}
    findings = {}
    for key, matched in results.items():
        for rule in buckets[key]:
            ident = (rule["group"], rule["name"])
            for item in matched:
                slot = findings.setdefault(ident, {}).setdefault(item["match"], [])
                slot.append(item)

    total_matches = 0
    unique_matches = 0
    files_with_matches = set()
    capped_rules = []
    finding_list = []
    group_stats = {}

    for ident in sorted(findings, key=lambda k: order.get(k, 1 << 30)):
        group_name, rule_name = ident
        by_value = findings[ident]
        ranked = sorted(by_value.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        if opts.max_matches > 0 and len(ranked) > opts.max_matches:
            capped_rules.append(f"{group_name}/{rule_name}")
            ranked = ranked[: opts.max_matches]

        rule_total = 0
        rule_files = set()
        for value, locations in ranked:
            seen = set()
            unique_locations = []
            for loc in locations:
                fingerprint = (loc["file"], loc["line"], loc["column"])
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                unique_locations.append(loc)
            rule_total += len(unique_locations)
            rule_files.update(loc["file"] for loc in unique_locations)
            kept = (
                unique_locations[: opts.max_locations]
                if opts.max_locations > 0
                else unique_locations
            )
            finding_list.append(
                {
                    "group": group_name,
                    "rule": rule_name,
                    "match": value,
                    "count": len(unique_locations),
                    "locations": [
                        {
                            "file": loc["file"],
                            "line": loc["line"],
                            "column": loc["column"],
                            "context": loc["context"],
                        }
                        for loc in kept
                    ],
                    "locations_omitted": len(unique_locations) - len(kept),
                }
            )
        total_matches += rule_total
        unique_matches += len(ranked)
        files_with_matches.update(rule_files)
        stats = group_stats.setdefault(group_name, {"group": group_name, "rules": []})
        stats["rules"].append(
            {
                "rule": rule_name,
                "unique": len(ranked),
                "total": rule_total,
                "files": len(rule_files),
            }
        )

    groups = []
    for stats in group_stats.values():
        groups.append(
            {
                "group": stats["group"],
                "unique": sum(r["unique"] for r in stats["rules"]),
                "total": sum(r["total"] for r in stats["rules"]),
                "rules": sorted(stats["rules"], key=lambda r: -r["total"]),
            }
        )

    return {
        "meta": {
            "tool": "seguridad-secretos-skill",
            "generated_at": datetime.now(timezone.utc)
            .astimezone()
            .replace(microsecond=0)
            .isoformat(),
            "rules_file": opts.rules,
            "targets": list(opts.targets),
            "ripgrep": {"path": opts.rg, "version": rg_version},
            "rules_total": len(rules),
            "rules_scanned": sum(len(v) for v in buckets.values()),
            "patterns_executed": len(buckets),
            "duration_ms": duration_ms,
            "options": {
                "context": opts.context,
                "max_count": opts.max_count,
                "max_filesize": opts.max_filesize,
                "max_locations": opts.max_locations,
                "max_matches": opts.max_matches,
                "ignore_ext": list(opts.ignore_ext),
                "timeout": opts.timeout,
                "jobs": opts.jobs,
            },
            "errors": errors,
            "capped_rules": capped_rules,
        },
        "summary": {
            "total_matches": total_matches,
            "unique_matches": unique_matches,
            "files_with_matches": len(files_with_matches),
            "rules_with_matches": len(findings),
            "groups": groups,
        },
        "findings": finding_list,
    }


def print_stdout_summary(report, out_path):
    summary = report["summary"]
    meta = report["meta"]
    print(f"reporte: {out_path}")
    print(
        "totales: {t} matches, {u} únicos, {f} archivos, {p} patrones, {ms}ms".format(
            t=summary["total_matches"],
            u=summary["unique_matches"],
            f=summary["files_with_matches"],
            p=meta["patterns_executed"],
            ms=meta["duration_ms"],
        )
    )
    for group in summary["groups"]:
        print(f"[{group['group']}] total={group['total']} unique={group['unique']}")
        for rule in group["rules"]:
            print(
                f"  - {rule['rule']}: total={rule['total']} "
                f"unique={rule['unique']} files={rule['files']}"
            )
    for error in meta["errors"]:
        print(f"error: {error['rules']}: {error['message']}", file=sys.stderr)
    if meta["capped_rules"]:
        print(f"truncadas: {', '.join(meta['capped_rules'])}", file=sys.stderr)



def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="hae_scan.py",
        description="Escanea archivos con reglas HaE vía ripgrep y escribe un reporte JSON.",
    )
    parser.add_argument("targets", nargs="*", help="archivos o directorios a escanear")
    parser.add_argument(
        "--rules",
        default=DEFAULT_RULES,
        help="ruta del archivo de reglas (JSON, o YAML si PyYAML está instalado)",
    )
    parser.add_argument("--group", action="append", default=[], help="filtrar por grupo (subcadena)")
    parser.add_argument("--rule", action="append", default=[], help="filtrar por nombre de regla (subcadena)")
    parser.add_argument("-o", "--out", default="", help="ruta de salida JSON, '-' para stdout")
    parser.add_argument("--rg", default="", help="ruta del binario de ripgrep")
    parser.add_argument("--jobs", type=int, default=8, help="procesos ripgrep en paralelo")
    parser.add_argument("--context", type=int, default=50, help="caracteres de contexto guardados por match")
    parser.add_argument("--max-count", type=int, default=0, help="rg --max-count por archivo, 0 = sin límite")
    parser.add_argument("--max-filesize", default="10M", help="rg --max-filesize, vacío = sin límite")
    parser.add_argument("--max-locations", type=int, default=5, help="ubicaciones guardadas por valor de match")
    parser.add_argument("--max-matches", type=int, default=200, help="valores de match guardados por regla")
    parser.add_argument("--timeout", type=int, default=180, help="timeout por patrón en segundos, 0 = sin límite")
    parser.add_argument("--ignore-ext", action="append", default=None, help="extensión a omitir, repetible")
    parser.add_argument("--list-rules", action="store_true", help="imprime las reglas como JSON y termina")
    return parser.parse_args(argv)


def resolve_out_path(out):
    if out == "-":
        return "-"
    if out:
        return os.path.abspath(out)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.abspath(os.path.join(".hae", f"hae-scan-{stamp}.json"))


def main(argv):
    opts = parse_args(argv)
    if opts.ignore_ext is None:
        opts.ignore_ext = list(DEFAULT_IGNORED_EXTENSIONS)

    if not os.path.isfile(opts.rules):
        sys.exit(f"archivo de reglas no encontrado: {opts.rules}")
    opts.rules = os.path.abspath(opts.rules)
    rules = load_rules(opts.rules)

    if opts.list_rules:
        json.dump(
            {"rules_file": opts.rules, "count": len(rules), "rules": rules},
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        print()
        return 0

    if not opts.targets:
        sys.exit("no se indicó un objetivo: pasa al menos un archivo o directorio a escanear")
    missing = [t for t in opts.targets if not os.path.exists(t)]
    if missing:
        sys.exit(f"objetivo no encontrado: {', '.join(missing)}")
    opts.targets = [os.path.abspath(t) for t in opts.targets]

    opts.rg = opts.rg or shutil.which("rg") or "rg"
    try:
        rg_version = (
            subprocess.run([opts.rg, "--version"], capture_output=True, text=True, check=True)
            .stdout.splitlines()[0]
            .strip()
        )
    except (OSError, subprocess.CalledProcessError, IndexError):
        sys.exit(f"ripgrep no está disponible en '{opts.rg}': instala ripgrep o pasa --rg RUTA")

    selected = select_rules(rules, opts.group, opts.rule)
    if not selected:
        sys.exit("no se seleccionó ninguna regla: revisa los filtros --group / --rule y las banderas 'loaded'")
    buckets = group_by_pattern(selected)

    started = time.monotonic()
    results = {}
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, opts.jobs)) as pool:
        futures = {
            pool.submit(scan_pattern, pattern, sensitive, opts): (pattern, sensitive)
            for pattern, sensitive in buckets
        }
        for future in futures:
            key = futures[future]
            matched, error = future.result()
            results[key] = matched
            if error:
                errors.append(
                    {
                        "rules": [f"{r['group']}/{r['name']}" for r in buckets[key]],
                        "message": error,
                    }
                )
    duration_ms = int((time.monotonic() - started) * 1000)

    report = build_report(
        selected, buckets, results, errors, opts, duration_ms, rg_version
    )

    out_path = resolve_out_path(opts.out)
    if out_path == "-":
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print_stdout_summary(report, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
